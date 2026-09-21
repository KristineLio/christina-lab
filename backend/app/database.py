from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.pool import StaticPool


DEFAULT_DATABASE_URL = "sqlite:///./christina_lab.sqlite3"


def normalize_database_url(database_url: str | None) -> str:
    value = (database_url or DEFAULT_DATABASE_URL).strip() or DEFAULT_DATABASE_URL
    if value.startswith("postgres://"):
        value = "postgresql+psycopg://" + value[len("postgres://"):]
    elif value.startswith("postgresql://") and not value.startswith("postgresql+psycopg://"):
        value = "postgresql+psycopg://" + value[len("postgresql://"):]

    database_name = os.getenv("DATABASE_NAME_OVERRIDE", "").strip()
    if database_name and value.startswith("postgresql+psycopg://"):
        parsed = urlsplit(value)
        value = urlunsplit(
            (parsed.scheme, parsed.netloc, f"/{database_name}", parsed.query, parsed.fragment)
        )
    return value


class CompatRow:
    """Small sqlite3.Row-compatible wrapper used by the storage layer."""

    def __init__(self, keys: Sequence[str], values: Sequence[Any]) -> None:
        self._keys = tuple(keys)
        self._values = tuple(values)
        self._mapping = dict(zip(self._keys, self._values))

    def __getitem__(self, key: int | str) -> Any:
        if isinstance(key, int):
            return self._values[key]
        return self._mapping[key]

    def keys(self) -> list[str]:
        return list(self._keys)

    def __iter__(self):
        return iter(self._values)


class CompatResult:
    def __init__(self, result: Any, connection: Connection, dialect: str) -> None:
        self._result = result
        self._connection = connection
        self._dialect = dialect
        self.rowcount = int(getattr(result, "rowcount", -1) or 0)
        self._keys = list(result.keys()) if getattr(result, "returns_rows", False) else []
        self._native_lastrowid = getattr(result, "lastrowid", None)

    def _wrap(self, row: Any | None) -> CompatRow | None:
        if row is None:
            return None
        return CompatRow(self._keys, list(row))

    def fetchone(self) -> CompatRow | None:
        return self._wrap(self._result.fetchone())

    def fetchall(self) -> list[CompatRow]:
        return [self._wrap(row) for row in self._result.fetchall()]

    @property
    def lastrowid(self) -> int | None:
        if self._native_lastrowid is not None:
            try:
                return int(self._native_lastrowid)
            except (TypeError, ValueError):
                pass
        if self._dialect == "postgresql":
            # The storage layer only reads lastrowid immediately after inserts
            # into BIGSERIAL-backed tables, so LASTVAL() is scoped to this
            # connection and transaction.
            value = self._connection.exec_driver_sql("SELECT LASTVAL()").scalar()
            return int(value) if value is not None else None
        return None


def _bind_qmarks(statement: str, params: Sequence[Any]) -> tuple[str, dict[str, Any]]:
    """Convert sqlite-style ? placeholders to SQLAlchemy named bindings.

    Existing Christina Lab queries all use positional qmark parameters. Keeping
    that API lets the storage code stay readable while supporting both SQLite
    and PostgreSQL.
    """
    if not params:
        return statement, {}

    pieces: list[str] = []
    bindings: dict[str, Any] = {}
    index = 0
    in_single = False
    in_double = False
    i = 0

    while i < len(statement):
        char = statement[i]
        if char == "'" and not in_double:
            if in_single and i + 1 < len(statement) and statement[i + 1] == "'":
                pieces.append("''")
                i += 2
                continue
            in_single = not in_single
            pieces.append(char)
        elif char == '"' and not in_single:
            in_double = not in_double
            pieces.append(char)
        elif char == "?" and not in_single and not in_double:
            if index >= len(params):
                raise ValueError("Not enough SQL parameters for qmark placeholders.")
            name = f"p{index}"
            pieces.append(f":{name}")
            bindings[name] = params[index]
            index += 1
        else:
            pieces.append(char)
        i += 1

    if index != len(params):
        raise ValueError("Too many SQL parameters for qmark placeholders.")
    return "".join(pieces), bindings


def _postgres_ddl(statement: str) -> str:
    return (
        statement.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
        .replace(" BLOB ", " BYTEA ")
        .replace(" BLOB\n", " BYTEA\n")
    )


class DatabaseConnection:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.dialect = engine.dialect.name
        self._context = None
        self._connection: Connection | None = None

    def __enter__(self) -> "DatabaseConnection":
        self._context = self.engine.begin()
        self._connection = self._context.__enter__()
        if self.dialect == "sqlite":
            self._connection.exec_driver_sql("PRAGMA foreign_keys = ON")
        return self

    def __exit__(self, exc_type, exc, tb) -> bool | None:
        if self._context is None:
            return None
        return self._context.__exit__(exc_type, exc, tb)

    @property
    def connection(self) -> Connection:
        if self._connection is None:
            raise RuntimeError("Database connection is not open.")
        return self._connection

    def execute(
        self,
        statement: str,
        params: Sequence[Any] | Mapping[str, Any] | None = None,
    ) -> CompatResult:
        if isinstance(params, Mapping):
            sql = statement
            bindings = dict(params)
        else:
            positional = tuple(params or ())
            sql, bindings = _bind_qmarks(statement, positional)
        result = self.connection.execute(text(sql), bindings)
        return CompatResult(result, self.connection, self.dialect)

    def executescript(self, script: str) -> None:
        text = _postgres_ddl(script) if self.dialect == "postgresql" else script
        for statement in text.split(";"):
            clean = statement.strip()
            if clean:
                self.connection.exec_driver_sql(clean)

    def columns(self, table: str) -> set[str]:
        if self.dialect == "sqlite":
            rows = self.connection.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
            return {str(row[1]) for row in rows}

        result = self.connection.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = :table
                """
            ),
            {"table": table},
        )
        return {str(row[0]) for row in result.fetchall()}


@dataclass
class DatabaseBackend:
    database_url: str

    def __post_init__(self) -> None:
        self.database_url = normalize_database_url(self.database_url)
        kwargs: dict[str, Any] = {"pool_pre_ping": True}

        if self.database_url == "sqlite:///:memory:":
            kwargs["connect_args"] = {"check_same_thread": False}
            kwargs["poolclass"] = StaticPool
        elif self.database_url.startswith("sqlite:///"):
            kwargs["connect_args"] = {"check_same_thread": False}

        self.engine = create_engine(self.database_url, **kwargs)

    @property
    def dialect(self) -> str:
        return self.engine.dialect.name

    @property
    def sqlite_path(self) -> str | None:
        if self.database_url == "sqlite:///:memory:":
            return ":memory:"
        prefix = "sqlite:///"
        if self.database_url.startswith(prefix):
            return self.database_url[len(prefix):] or "./christina_lab.sqlite3"
        return None

    def connect(self) -> DatabaseConnection:
        return DatabaseConnection(self.engine)

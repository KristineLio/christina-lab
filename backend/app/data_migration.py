from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Any, Callable

from .database import DatabaseConnection


DATA_TABLES: tuple[str, ...] = (
    "videos",
    "video_snapshots",
    "video_analyses",
    "saved_research",
    "ideas",
    "idea_documents",
    "experiments",
)

SERIAL_TABLES: tuple[str, ...] = (
    "video_snapshots",
    "video_analyses",
    "ideas",
    "idea_documents",
    "experiments",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _encode(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"__base64__": base64.b64encode(bytes(value)).decode("ascii")}
    return value


def _decode(value: Any) -> Any:
    if isinstance(value, dict) and set(value) == {"__base64__"}:
        return base64.b64decode(value["__base64__"])
    return value


def export_database(connect: Callable[[], DatabaseConnection]) -> dict:
    tables: dict[str, list[dict[str, Any]]] = {}
    with connect() as db:
        for table in DATA_TABLES:
            rows = db.execute(f"SELECT * FROM {table}").fetchall()
            tables[table] = [
                {key: _encode(row[key]) for key in row.keys()}
                for row in rows
            ]

    return {
        "format": "christina-lab-database-export",
        "version": 1,
        "generatedAt": _now_iso(),
        "tables": tables,
        "counts": {table: len(rows) for table, rows in tables.items()},
    }


def import_database(
    connect: Callable[[], DatabaseConnection],
    payload: dict,
    *,
    replace: bool = False,
) -> dict:
    if payload.get("format") != "christina-lab-database-export":
        raise ValueError("Unsupported migration export format.")
    tables = payload.get("tables")
    if not isinstance(tables, dict):
        raise ValueError("Migration export is missing tables.")

    imported: dict[str, int] = {}
    with connect() as db:
        existing = {
            table: int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in DATA_TABLES
        }
        if not replace and any(existing.values()):
            populated = ", ".join(
                f"{table}={count}" for table, count in existing.items() if count
            )
            raise ValueError(
                "Target database is not empty. Refusing migration without replace=True: "
                + populated
            )

        if replace:
            for table in reversed(DATA_TABLES):
                db.execute(f"DELETE FROM {table}")

        for table in DATA_TABLES:
            rows = tables.get(table, [])
            if not isinstance(rows, list):
                raise ValueError(f"Invalid rows for table {table}.")
            for row in rows:
                if not isinstance(row, dict) or not row:
                    continue
                columns = list(row.keys())
                placeholders = ", ".join("?" for _ in columns)
                column_sql = ", ".join(columns)
                values = tuple(_decode(row[column]) for column in columns)
                db.execute(
                    f"INSERT INTO {table} ({column_sql}) VALUES ({placeholders})",
                    values,
                )
            imported[table] = len(rows)

        if db.dialect == "postgresql":
            for table in SERIAL_TABLES:
                db.execute(
                    f"""
                    SELECT setval(
                        pg_get_serial_sequence('{table}', 'id'),
                        COALESCE((SELECT MAX(id) FROM {table}), 1),
                        EXISTS(SELECT 1 FROM {table})
                    )
                    """
                )

    return {
        "importedAt": _now_iso(),
        "counts": imported,
        "totalRows": sum(imported.values()),
    }

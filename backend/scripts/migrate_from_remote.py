from __future__ import annotations

import os
import sys

import httpx

from backend.app.data_migration import import_database
from backend.app.storage import SnapshotStore


def main() -> int:
    source_url = os.getenv("MIGRATION_SOURCE_URL", "").strip()
    token = os.getenv("MIGRATION_EXPORT_TOKEN", "").strip()
    database_url = os.getenv("DATABASE_URL", "").strip()

    if not source_url or not token or not database_url:
        print(
            "MIGRATION_SOURCE_URL, MIGRATION_EXPORT_TOKEN and DATABASE_URL are required.",
            file=sys.stderr,
        )
        return 2

    response = httpx.get(
        source_url.rstrip("/") + "/api/admin/migration-export",
        headers={"X-Migration-Token": token},
        timeout=60.0,
    )
    response.raise_for_status()
    payload = response.json()

    store = SnapshotStore(database_url)
    result = import_database(store._connect, payload)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

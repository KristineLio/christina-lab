from datetime import datetime, timezone
import os

import pytest

from backend.app.storage import SnapshotStore


POSTGRES_URL = os.getenv("TEST_POSTGRES_URL", "").strip()


@pytest.mark.skipif(not POSTGRES_URL, reason="TEST_POSTGRES_URL is not configured")
def test_postgres_storage_roundtrip():
    store = SnapshotStore(POSTGRES_URL)

    # Keep the CI database deterministic if the job is retried.
    with store._connect() as db:
        for table in (
            "experiments",
            "idea_documents",
            "ideas",
            "workspace_saved_research",
            "saved_research",
            "video_analyses",
            "video_snapshots",
            "videos",
        ):
            db.execute(f"DELETE FROM {table}")

    observed = datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc)
    store.record_snapshots(
        [
            {
                "id": "pg-video-1",
                "channelId": "pg-channel",
                "channel": "Postgres Channel",
                "title": "Postgres migration test",
                "publishedAt": observed,
                "type": "Long-form",
                "liveStatus": "none",
                "durationSeconds": 600,
                "views": 1234,
                "likes": 100,
                "comments": 20,
                "subscribers": 5000,
            }
        ],
        observed_at=observed,
        min_interval_minutes=0,
    )

    research = store.save_research(
        "pg-video-1",
        why="Portable persistence",
        adapt="Keep the workflow",
        angle="SQLite to Postgres",
        collection="Migration tests",
    )
    assert research["videoId"] == "pg-video-1"

    idea = store.create_idea(
        source_video_id="pg-video-1",
        title="Postgres-backed creator workflow",
        status="Ready",
    )
    assert idea["id"] > 0

    document = store.save_idea_document(
        idea["id"],
        kind="script",
        filename="script.txt",
        content_type="text/plain",
        content=b"hello postgres",
    )
    loaded = store.get_idea_document(document["id"])
    assert loaded is not None
    assert loaded["content"] == b"hello postgres"

    experiment = store.create_experiment(idea_id=idea["id"], decision="TEST")
    assert experiment["ideaId"] == idea["id"]

    workflow = store.workflow_summary()
    assert workflow["summary"]["savedResearch"] == 1
    assert workflow["summary"]["ideas"] == 1
    assert workflow["summary"]["experiments"] == 1

    with store._connect() as db:
        versions = [
            int(row["version"])
            for row in db.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        ]
    assert versions == [1, 2, 3, 4, 5]

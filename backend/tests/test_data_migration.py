from datetime import datetime, timezone

from backend.app.data_migration import export_database, import_database
from backend.app.storage import SnapshotStore


def _seed(store: SnapshotStore) -> tuple[int, int]:
    observed = datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc)
    store.record_snapshots(
        [
            {
                "id": "migrate-video",
                "channelId": "migrate-channel",
                "channel": "Migration Channel",
                "title": "Migration reference",
                "publishedAt": observed,
                "type": "Long-form",
                "liveStatus": "none",
                "durationSeconds": 500,
                "views": 500,
                "likes": 50,
                "comments": 5,
                "subscribers": 1000,
            }
        ],
        observed_at=observed,
        min_interval_minutes=0,
    )
    store.record_analyses(
        [
            {
                "id": "migrate-video",
                "opportunity": 77,
                "outlier": 2.4,
                "baseline": 200,
                "baselineMethod": "test",
                "baselineSampleSize": 4,
                "viewsDay": 12000,
                "engagement": 4.5,
                "viewsSub": 0.5,
            }
        ],
        topic="migration",
        observed_at=observed,
    )
    store.save_research(
        "migrate-video",
        why="Keep this",
        adapt="Adapt this",
        angle="Migration",
        collection="Migration",
    )
    idea = store.create_idea(
        source_video_id="migrate-video",
        title="Migrated idea",
        status="Ready",
    )
    document = store.save_idea_document(
        idea["id"],
        kind="script",
        filename="script.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        content=b"docx-bytes",
    )
    store.create_experiment(idea_id=idea["id"], decision="TEST")
    return idea["id"], document["id"]


def test_export_import_roundtrip_preserves_workflow_and_blobs(tmp_path):
    source = SnapshotStore(f"sqlite:///{tmp_path / 'source.sqlite3'}")
    target = SnapshotStore(f"sqlite:///{tmp_path / 'target.sqlite3'}")
    idea_id, document_id = _seed(source)

    payload = export_database(source._connect)
    result = import_database(target._connect, payload)

    assert result["totalRows"] == sum(payload["counts"].values())
    assert target.get_idea(idea_id)["title"] == "Migrated idea"
    loaded = target.get_idea_document(document_id)
    assert loaded is not None
    assert loaded["content"] == b"docx-bytes"
    assert target.workflow_summary()["summary"]["experiments"] == 1


def test_import_refuses_nonempty_target_without_replace(tmp_path):
    source = SnapshotStore(f"sqlite:///{tmp_path / 'source.sqlite3'}")
    target = SnapshotStore(f"sqlite:///{tmp_path / 'target.sqlite3'}")
    _seed(source)
    _seed(target)

    payload = export_database(source._connect)

    try:
        import_database(target._connect, payload)
    except ValueError as exc:
        assert "Target database is not empty" in str(exc)
    else:
        raise AssertionError("Expected non-empty target protection")

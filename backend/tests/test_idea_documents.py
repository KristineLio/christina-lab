from backend.app.storage import SnapshotStore


def test_idea_documents_round_trip(tmp_path):
    db = tmp_path / "christina_lab.sqlite3"
    store = SnapshotStore(f"sqlite:///{db}")

    idea = store.create_idea(
        title="Weather App video",
        topic="From Code to Career",
        status="Ready",
    )
    assert idea["documentCount"] == 0

    saved = store.save_idea_document(
        idea["id"],
        kind="script",
        filename="weather-script.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        content=b"docx-bytes",
    )

    assert saved["ideaId"] == idea["id"]
    assert saved["kind"] == "script"
    assert saved["filename"] == "weather-script.docx"
    assert saved["sizeBytes"] == len(b"docx-bytes")

    documents = store.list_idea_documents(idea["id"])
    assert len(documents) == 1
    assert "content" not in documents[0]

    loaded = store.get_idea_document(saved["id"])
    assert loaded is not None
    assert loaded["content"] == b"docx-bytes"

    refreshed = store.get_idea(idea["id"])
    assert refreshed is not None
    assert refreshed["documentCount"] == 1

    assert store.delete_idea_document(saved["id"]) is True
    assert store.list_idea_documents(idea["id"]) == []
    assert store.get_idea_document(saved["id"]) is None

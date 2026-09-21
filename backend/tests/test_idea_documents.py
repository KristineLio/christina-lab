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


def test_idea_document_cloud_metadata(tmp_path):
    db = tmp_path / "christina_lab.sqlite3"
    store = SnapshotStore(f"sqlite:///{db}")
    idea = store.create_idea(title="Cloud export")
    doc = store.save_idea_document(
        idea["id"],
        kind="script",
        filename="script.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        content=b"docx",
    )

    updated = store.update_idea_document_cloud(
        doc["id"],
        provider="google_docs",
        file_id="google-file-123",
        url="https://docs.google.com/document/d/google-file-123/edit",
    )
    assert updated is not None
    assert updated["cloudProvider"] == "google_docs"
    assert updated["cloudFileId"] == "google-file-123"
    assert updated["cloudUrl"].endswith("/edit")
    assert updated["cloudUploadedAt"]

    listed = store.list_idea_documents(idea["id"])
    assert listed[0]["cloudProvider"] == "google_docs"
    assert listed[0]["cloudFileId"] == "google-file-123"

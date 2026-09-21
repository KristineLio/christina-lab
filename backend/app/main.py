from __future__ import annotations

import base64
import binascii
import os
import secrets
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from .data_migration import export_database
from .storage import SnapshotStore
from .youtube import YouTubeAPIError, YouTubeClient


load_dotenv()

FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
snapshot_store = SnapshotStore()

app = FastAPI(
    title="Christina Lab API",
    version="0.1.0",
    description="Backend for YouTube creator intelligence experiments.",
)

allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5500,http://127.0.0.1:5500",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


class ResearchUpdate(BaseModel):
    why: str | None = Field(default=None, max_length=4000)
    adapt: str | None = Field(default=None, max_length=4000)
    angle: str | None = Field(default=None, max_length=4000)
    collection: str | None = Field(default=None, max_length=120)


class IdeaCreate(BaseModel):
    sourceVideoId: str | None = Field(default=None, max_length=40)
    title: str = Field(min_length=1, max_length=240)
    hook: str = Field(default="", max_length=500)
    topic: str = Field(default="", max_length=160)
    contentType: str = Field(default="Long-form", max_length=40)
    angle: str = Field(default="", max_length=1000)
    audience: str = Field(default="", max_length=500)
    hypothesis: str = Field(default="", max_length=4000)
    notes: str = Field(default="", max_length=4000)
    priority: str = Field(default="Med", max_length=20)
    status: str = Field(default="Draft", max_length=20)


class IdeaUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    hook: str | None = Field(default=None, max_length=500)
    topic: str | None = Field(default=None, max_length=160)
    contentType: str | None = Field(default=None, max_length=40)
    angle: str | None = Field(default=None, max_length=1000)
    audience: str | None = Field(default=None, max_length=500)
    hypothesis: str | None = Field(default=None, max_length=4000)
    notes: str | None = Field(default=None, max_length=4000)
    priority: str | None = Field(default=None, max_length=20)
    status: str | None = Field(default=None, max_length=20)


class IdeaDocumentUpload(BaseModel):
    kind: str = Field(default="other", max_length=40)
    filename: str = Field(min_length=1, max_length=240)
    contentType: str = Field(default="application/octet-stream", max_length=160)
    dataBase64: str = Field(min_length=1)


class IdeaDocumentCloudUpdate(BaseModel):
    provider: str = Field(min_length=1, max_length=40)
    fileId: str = Field(min_length=1, max_length=240)
    url: str = Field(min_length=1, max_length=1000)


class ExperimentCreate(BaseModel):
    ideaId: int = Field(ge=1)
    name: str | None = Field(default=None, max_length=240)
    hypothesis: str | None = Field(default=None, max_length=4000)
    status: str | None = Field(default=None, max_length=20)
    decision: str = Field(default="UNDECIDED", max_length=20)


class ExperimentUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=240)
    hypothesis: str | None = Field(default=None, max_length=4000)
    status: str | None = Field(default=None, max_length=20)
    publishedAt: str | None = Field(default=None, max_length=40)
    v24: int | None = Field(default=None, ge=0)
    v7: int | None = Field(default=None, ge=0)
    retention: float | None = Field(default=None, ge=0, le=100)
    subs: int | None = None
    ctr: float | None = Field(default=None, ge=0, le=100)
    result: str | None = Field(default=None, max_length=4000)
    decision: str | None = Field(default=None, max_length=20)
    lesson: str | None = Field(default=None, max_length=4000)
    next: str | None = Field(default=None, max_length=4000)


IDEA_STATUSES = {"Draft", "Ready", "Published"}
EXPERIMENT_STATUSES = {"Draft", "Ready", "Published"}
EXPERIMENT_DECISIONS = {"UNDECIDED", "GO", "TEST", "HOLD"}
PRIORITIES = {"High", "Med", "Low"}
IDEA_DOCUMENT_KINDS = {"script", "plan", "reference", "other"}
IDEA_DOCUMENT_EXTENSIONS = {".docx", ".pdf", ".md", ".txt"}
IDEA_DOCUMENT_MAX_BYTES = 5 * 1024 * 1024


def _model_changes(model: BaseModel) -> dict:
    return model.model_dump(exclude_unset=True)


def _validate_choice(value: str | None, allowed: set[str], label: str) -> None:
    if value is not None and value not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"{label} must be one of: {', '.join(sorted(allowed))}",
        )


@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok",
        "youtubeConfigured": bool(os.getenv("YOUTUBE_API_KEY")),
        "googleDocsConfigured": bool(os.getenv("GOOGLE_OAUTH_CLIENT_ID")),
        "snapshotStore": snapshot_store.stats(),
    }


@app.get("/api/admin/migration-export")
async def migration_export(
    x_migration_token: str | None = Header(default=None),
) -> dict:
    """One-time, token-protected export used for SQLite -> PostgreSQL migration.

    The endpoint is disabled unless MIGRATION_EXPORT_TOKEN is configured.
    Keep the token only for the migration window, then remove it.
    """
    expected = os.getenv("MIGRATION_EXPORT_TOKEN", "").strip()
    if not expected:
        raise HTTPException(status_code=404, detail="Migration export is disabled.")
    provided = (x_migration_token or "").strip()
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=403, detail="Invalid migration token.")
    return export_database(snapshot_store._connect)


@app.get("/api/config/public")
async def public_config() -> dict:
    # OAuth client IDs are public identifiers. Secrets/tokens never belong in
    # this endpoint or in the browser bundle.
    return {
        "googleOAuthClientId": os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip(),
        "googleDriveScope": "https://www.googleapis.com/auth/drive.file",
    }


@app.get("/api/discover")
async def discover(
    q: str = Query(..., min_length=2, max_length=120),
    max_results: int = Query(25, ge=1, le=50),
    published_after_days: int = Query(7, ge=0, le=3650),
    mode: str = Query("trend", pattern="^(trend|reference)$"),
) -> dict:
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="YOUTUBE_API_KEY is not configured on the backend.",
        )

    try:
        return await YouTubeClient(api_key, snapshot_store=snapshot_store).discover(
            query=q.strip(),
            max_results=max_results,
            published_after_days=published_after_days,
            mode=mode,
        )
    except YouTubeAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc



@app.get("/api/snapshots/stats")
async def snapshot_stats() -> dict:
    return snapshot_store.stats()


@app.get("/api/videos/{video_id}/snapshots")
async def video_snapshots(video_id: str) -> dict:
    snapshots = snapshot_store.video_snapshots(video_id)
    return {
        "videoId": video_id,
        "count": len(snapshots),
        "snapshots": snapshots,
    }



@app.get("/api/dashboard")
async def dashboard() -> dict:
    return snapshot_store.dashboard_summary()


@app.get("/api/patterns")
async def patterns() -> dict:
    return snapshot_store.patterns_summary()



@app.get("/api/workflow")
async def workflow() -> dict:
    return snapshot_store.workflow_summary()


@app.get("/api/research")
async def saved_research() -> dict:
    items = snapshot_store.list_saved_research()
    return {"count": len(items), "items": items}


@app.put("/api/research/{video_id}")
async def save_research(video_id: str, payload: ResearchUpdate) -> dict:
    try:
        return snapshot_store.save_research(
            video_id,
            why=payload.why,
            adapt=payload.adapt,
            angle=payload.angle,
            collection=payload.collection,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/research/{video_id}")
async def delete_research(video_id: str) -> dict:
    deleted = snapshot_store.remove_saved_research(video_id)
    return {"videoId": video_id, "deleted": deleted}


@app.get("/api/ideas")
async def ideas() -> dict:
    items = snapshot_store.list_ideas()
    return {"count": len(items), "items": items}


@app.post("/api/ideas", status_code=201)
async def create_idea(payload: IdeaCreate) -> dict:
    _validate_choice(payload.status, IDEA_STATUSES, "Idea status")
    _validate_choice(payload.priority, PRIORITIES, "Priority")

    if payload.sourceVideoId:
        try:
            snapshot_store.save_research(payload.sourceVideoId)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        return snapshot_store.create_idea(
            title=payload.title,
            source_video_id=payload.sourceVideoId,
            hook=payload.hook,
            topic=payload.topic,
            content_type=payload.contentType,
            angle=payload.angle,
            audience=payload.audience,
            hypothesis=payload.hypothesis,
            notes=payload.notes,
            priority=payload.priority,
            status=payload.status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/api/ideas/{idea_id}")
async def update_idea(idea_id: int, payload: IdeaUpdate) -> dict:
    changes = _model_changes(payload)
    _validate_choice(changes.get("status"), IDEA_STATUSES, "Idea status")
    _validate_choice(changes.get("priority"), PRIORITIES, "Priority")
    item = snapshot_store.update_idea(idea_id, changes)
    if item is None:
        raise HTTPException(status_code=404, detail="Idea not found.")
    return item


@app.get("/api/ideas/{idea_id}/documents")
async def idea_documents(idea_id: int) -> dict:
    try:
        items = snapshot_store.list_idea_documents(idea_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"count": len(items), "items": items}


@app.post("/api/ideas/{idea_id}/documents", status_code=201)
async def upload_idea_document(idea_id: int, payload: IdeaDocumentUpload) -> dict:
    kind = payload.kind.strip().lower() or "other"
    _validate_choice(kind, IDEA_DOCUMENT_KINDS, "Document kind")

    filename = Path(payload.filename).name.strip()
    extension = Path(filename).suffix.lower()
    if not filename or extension not in IDEA_DOCUMENT_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail="Upload a .docx, .pdf, .md, or .txt file.",
        )

    try:
        content = base64.b64decode(payload.dataBase64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=422, detail="File payload is not valid base64.") from exc

    if len(content) > IDEA_DOCUMENT_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Idea documents are limited to 5 MB each.")

    try:
        return snapshot_store.save_idea_document(
            idea_id,
            kind=kind,
            filename=filename,
            content_type=payload.contentType or "application/octet-stream",
            content=content,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/idea-documents/{document_id}")
async def download_idea_document(document_id: int) -> Response:
    item = snapshot_store.get_idea_document(document_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    safe_name = Path(item["filename"]).name
    disposition = "attachment; filename*=UTF-8''" + quote(safe_name)
    return Response(
        content=item["content"],
        media_type=item["contentType"] or "application/octet-stream",
        headers={"Content-Disposition": disposition},
    )


@app.patch("/api/idea-documents/{document_id}/cloud")
async def update_idea_document_cloud(document_id: int, payload: IdeaDocumentCloudUpdate) -> dict:
    provider = payload.provider.strip().lower()
    if provider != "google_docs":
        raise HTTPException(status_code=422, detail="Unsupported cloud provider.")
    item = snapshot_store.update_idea_document_cloud(
        document_id,
        provider=provider,
        file_id=payload.fileId.strip(),
        url=payload.url.strip(),
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return item


@app.delete("/api/idea-documents/{document_id}")
async def delete_idea_document(document_id: int) -> dict:
    return {
        "documentId": document_id,
        "deleted": snapshot_store.delete_idea_document(document_id),
    }


@app.get("/api/experiments")
async def experiments() -> dict:
    items = snapshot_store.list_experiments()
    return {"count": len(items), "items": items}


@app.post("/api/experiments", status_code=201)
async def create_experiment(payload: ExperimentCreate) -> dict:
    _validate_choice(payload.status, EXPERIMENT_STATUSES, "Experiment status")
    _validate_choice(payload.decision, EXPERIMENT_DECISIONS, "Decision")
    try:
        return snapshot_store.create_experiment(
            idea_id=payload.ideaId,
            name=payload.name,
            hypothesis=payload.hypothesis,
            status=payload.status,
            decision=payload.decision,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/experiments/{experiment_id}")
async def experiment(experiment_id: int) -> dict:
    item = snapshot_store.get_experiment(experiment_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Experiment not found.")
    return item


@app.patch("/api/experiments/{experiment_id}")
async def update_experiment(experiment_id: int, payload: ExperimentUpdate) -> dict:
    changes = _model_changes(payload)
    _validate_choice(changes.get("status"), EXPERIMENT_STATUSES, "Experiment status")
    _validate_choice(changes.get("decision"), EXPERIMENT_DECISIONS, "Decision")
    item = snapshot_store.update_experiment(experiment_id, changes)
    if item is None:
        raise HTTPException(status_code=404, detail="Experiment not found.")
    return item


# Serve the lightweight frontend from the same Render service for the alpha deployment.
@app.get("/", include_in_schema=False)
async def frontend_index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


@app.get("/{asset_name}", include_in_schema=False)
async def frontend_asset(asset_name: str):
    allowed_assets = {"styles.css", "data.js", "app.js", "thumb.jpg"}
    if asset_name not in allowed_assets:
        raise HTTPException(status_code=404, detail="Not found.")
    return FileResponse(os.path.join(FRONTEND_DIR, asset_name))

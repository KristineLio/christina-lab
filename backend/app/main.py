from __future__ import annotations

import base64
import json
import binascii
import os
import re
import secrets
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from .creator_agent import (
    CreatorAgentError,
    creator_agent_configured,
    creator_agent_model,
    creator_agent_provider,
    analyze_short_transcript,
    generate_idea_from_saved_research,
    generate_idea_production_docs,
    generate_package,
    generate_short_package,
    load_github_repo_context,
    load_public_youtube_transcript,
    provider_status,
    relevant_saved_research,
    compact_youtube_sources,
    research_angles,
)
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


class SavedResearchAgentIdeaRequest(BaseModel):
    contentType: str = Field(min_length=1, max_length=40)


class IdeaAgentProductionDocsRequest(BaseModel):
    platform: str = Field(min_length=1, max_length=40)
    targetDurationMinutes: int | None = Field(default=None, ge=3, le=20)


class CreatorAgentResearchRequest(BaseModel):
    project: str = Field(min_length=2, max_length=240)
    goal: str = Field(
        default="Document my progress from code to career by showing what I build, learn, and test.",
        max_length=1000,
    )
    topic: str = Field(default="", max_length=240)
    repoUrl: str | None = Field(default=None, max_length=1000)
    contentType: str = Field(default="Long-form", max_length=40)


class CreatorAgentAngle(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=300)
    hook: str = Field(default="", max_length=1000)
    positioning: str = Field(default="", max_length=3000)
    whyThisCouldWork: str = Field(default="", max_length=3000)
    whatMakesItYours: str = Field(default="", max_length=3000)
    sourceIds: list[str] = Field(default_factory=list)


class CreatorAgentSource(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    title: str = Field(default="", max_length=500)
    channel: str = Field(default="", max_length=300)
    url: str = Field(default="", max_length=1000)
    type: str = Field(default="", max_length=80)
    views: int = Field(default=0, ge=0)
    opportunity: float | int | None = None
    outlier: float | None = None
    engagement: float | None = None
    topic: str = Field(default="", max_length=300)
    whyUseful: str = Field(default="", max_length=3000)
    useFor: str = Field(default="", max_length=3000)
    caution: str = Field(default="", max_length=3000)


class CreatorAgentPackageRequest(CreatorAgentResearchRequest):
    angle: CreatorAgentAngle
    sourceMaterials: list[CreatorAgentSource] = Field(default_factory=list)


class CreatorAgentShortMoment(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    startSeconds: float = Field(ge=0)
    endSeconds: float = Field(ge=0)
    frameTimeSeconds: float = Field(ge=0)
    label: str = Field(default="", max_length=240)
    sourceParaphrase: str = Field(default="", max_length=2000)
    mechanism: str = Field(default="", max_length=2000)
    whyStrong: str = Field(default="", max_length=3000)
    shortDirection: str = Field(default="", max_length=3000)


class CreatorAgentShortAnalyzeRequest(BaseModel):
    source: CreatorAgentSource
    transcript: str = Field(min_length=20, max_length=50000)
    platform: str = Field(default="YouTube Shorts", max_length=80)


class CreatorAgentShortGenerateRequest(BaseModel):
    source: CreatorAgentSource
    transcript: str = Field(min_length=20, max_length=50000)
    moment: CreatorAgentShortMoment
    platform: str = Field(default="YouTube Shorts", max_length=80)
    durationSeconds: int = Field(default=8, ge=4, le=15)
    hasReferenceFrame: bool = False


class ExperimentCreate(BaseModel):
    ideaId: int = Field(ge=1)
    name: str | None = Field(default=None, max_length=240)
    hypothesis: str | None = Field(default=None, max_length=4000)
    status: str | None = Field(default=None, max_length=20)
    decision: str = Field(default="UNDECIDED", max_length=20)


class ExperimentUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=240)
    topic: str | None = Field(default=None, max_length=240)
    format: str | None = Field(default=None, max_length=40)
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
IDEA_DOCUMENT_KINDS = {"script", "plan", "reference", "video_prompt", "photo_reference", "other"}
IDEA_DOCUMENT_EXTENSIONS = {".docx", ".pdf", ".md", ".txt", ".png", ".jpg", ".jpeg", ".webp"}
IDEA_DOCUMENT_MAX_BYTES = 5 * 1024 * 1024


WORKSPACE_ACCESS_KEY_PATTERN = re.compile(r"^clw_[A-Za-z0-9_-]{24,100}$")


def _workspace_id(raw: str | None) -> str:
    """Resolve an opaque alpha access key to an isolated creator workspace."""

    value = str(raw or "").strip()
    if not value:
        raise HTTPException(
            status_code=401,
            detail="Private alpha workspace key required. Open Christina Lab from your owner or tester link.",
        )
    if not WORKSPACE_ACCESS_KEY_PATTERN.fullmatch(value):
        raise HTTPException(status_code=400, detail="Invalid workspace key.")
    return snapshot_store.workspace_id_for_access_key(value)


def _model_changes(model: BaseModel) -> dict:
    return model.model_dump(exclude_unset=True)


def _validate_choice(value: str | None, allowed: set[str], label: str) -> None:
    if value is not None and value not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"{label} must be one of: {', '.join(sorted(allowed))}",
        )


@app.post("/api/workspace/claim-owner")
async def claim_owner_workspace() -> dict:
    access_key = snapshot_store.claim_owner_workspace()
    if access_key is None:
        raise HTTPException(
            status_code=409,
            detail="The owner workspace has already been claimed. Use the saved owner recovery link.",
        )
    return {
        "accessKey": access_key,
        "workspaceType": "owner",
        "message": "Owner workspace claimed. Save the recovery link shown in Christina Lab.",
    }


@app.get("/api/workspace/status")
async def workspace_status(
    x_christina_workspace: str | None = Header(default=None, alias="X-Christina-Workspace"),
) -> dict:
    access_key = str(x_christina_workspace or "").strip()
    workspace_id = _workspace_id(access_key)
    return {
        "workspaceType": "owner" if workspace_id == "owner" else "tester",
        "workspaceId": workspace_id,
        "isOwner": workspace_id == "owner",
        "isPrivateAlpha": True,
    }


@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok",
        "youtubeConfigured": bool(os.getenv("YOUTUBE_API_KEY")),
        "googleDocsConfigured": bool(os.getenv("GOOGLE_OAUTH_CLIENT_ID")),
        "creatorAgentConfigured": creator_agent_configured(),
        "creatorAgentProvider": creator_agent_provider(),
        "creatorAgentModel": creator_agent_model() if creator_agent_configured() else None,
        "creatorAgentProviders": provider_status(),
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
        "youtubeConfigured": bool(os.getenv("YOUTUBE_API_KEY")),
        "googleOAuthClientId": os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip(),
        "googleDriveScope": "https://www.googleapis.com/auth/drive.file",
        "creatorAgentConfigured": creator_agent_configured(),
        "creatorAgentProvider": creator_agent_provider(),
        "creatorAgentModel": creator_agent_model() if creator_agent_configured() else "",
        "creatorAgentProviders": provider_status(),
        "workspaceIsolation": "private-alpha-key",
        "googleTokenStorage": "browser-memory",
        "agentCanPublish": False,
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
async def workflow(
    x_christina_workspace: str | None = Header(default=None, alias="X-Christina-Workspace"),
) -> dict:
    return snapshot_store.workflow_summary(
        workspace_id=_workspace_id(x_christina_workspace)
    )


@app.get("/api/research")
async def saved_research(
    x_christina_workspace: str | None = Header(default=None, alias="X-Christina-Workspace"),
) -> dict:
    workspace_id = _workspace_id(x_christina_workspace)
    items = snapshot_store.list_saved_research(workspace_id=workspace_id)
    return {"count": len(items), "items": items}


@app.put("/api/research/{video_id}")
async def save_research(
    video_id: str,
    payload: ResearchUpdate,
    x_christina_workspace: str | None = Header(default=None, alias="X-Christina-Workspace"),
) -> dict:
    workspace_id = _workspace_id(x_christina_workspace)
    try:
        return snapshot_store.save_research(
            video_id,
            why=payload.why,
            adapt=payload.adapt,
            angle=payload.angle,
            collection=payload.collection,
            workspace_id=workspace_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/research/{video_id}")
async def delete_research(
    video_id: str,
    x_christina_workspace: str | None = Header(default=None, alias="X-Christina-Workspace"),
) -> dict:
    deleted = snapshot_store.remove_saved_research(
        video_id,
        workspace_id=_workspace_id(x_christina_workspace),
    )
    return {"videoId": video_id, "deleted": deleted}


@app.post("/api/research/{video_id}/agent-idea", status_code=201)
async def create_agent_idea_from_saved_research(
    video_id: str,
    payload: SavedResearchAgentIdeaRequest,
    x_christina_workspace: str | None = Header(default=None, alias="X-Christina-Workspace"),
) -> dict:
    if not creator_agent_configured():
        raise HTTPException(
            status_code=503,
            detail="Creator Agent is not configured. Add a key for the selected AI provider.",
        )

    content_type = payload.contentType.strip()
    if content_type not in {"Short", "Long-form"}:
        raise HTTPException(
            status_code=422,
            detail="Choose either Short or Long-form before generating the idea.",
        )

    workspace_id = _workspace_id(x_christina_workspace)
    saved = next(
        (
            item
            for item in snapshot_store.list_saved_research(workspace_id=workspace_id)
            if str(item.get("videoId") or item.get("id") or "") == video_id
        ),
        None,
    )
    if saved is None:
        raise HTTPException(status_code=404, detail="Saved research item not found.")

    try:
        generated = await generate_idea_from_saved_research(
            saved_research=saved,
            content_type=content_type,
        )
    except CreatorAgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    idea = snapshot_store.create_idea(
        title=str(generated.get("title") or saved.get("title") or "Creator idea").strip(),
        source_video_id=video_id,
        hook=str(generated.get("hook") or "").strip(),
        topic=str(generated.get("topic") or saved.get("topic") or "").strip(),
        content_type=content_type,
        angle=str(generated.get("angle") or saved.get("angle") or "").strip(),
        audience=str(generated.get("audience") or "").strip(),
        hypothesis=str(generated.get("hypothesis") or "").strip(),
        notes=str(generated.get("notes") or "").strip(),
        priority="Med",
        status="Draft",
        workspace_id=workspace_id,
    )

    return {
        "idea": idea,
        "contentType": content_type,
        "provider": generated.get("_agentProvider") or creator_agent_provider(),
        "model": generated.get("_agentModel") or creator_agent_model(),
    }


@app.get("/api/ideas")
async def ideas(
    x_christina_workspace: str | None = Header(default=None, alias="X-Christina-Workspace"),
) -> dict:
    items = snapshot_store.list_ideas(
        workspace_id=_workspace_id(x_christina_workspace)
    )
    return {"count": len(items), "items": items}


@app.post("/api/ideas", status_code=201)
async def create_idea(
    payload: IdeaCreate,
    x_christina_workspace: str | None = Header(default=None, alias="X-Christina-Workspace"),
) -> dict:
    workspace_id = _workspace_id(x_christina_workspace)
    _validate_choice(payload.status, IDEA_STATUSES, "Idea status")
    _validate_choice(payload.priority, PRIORITIES, "Priority")

    if payload.sourceVideoId:
        try:
            snapshot_store.save_research(
                payload.sourceVideoId,
                workspace_id=workspace_id,
            )
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
            workspace_id=workspace_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/api/ideas/{idea_id}")
async def update_idea(
    idea_id: int,
    payload: IdeaUpdate,
    x_christina_workspace: str | None = Header(default=None, alias="X-Christina-Workspace"),
) -> dict:
    changes = _model_changes(payload)
    _validate_choice(changes.get("status"), IDEA_STATUSES, "Idea status")
    _validate_choice(changes.get("priority"), PRIORITIES, "Priority")
    item = snapshot_store.update_idea(
        idea_id,
        changes,
        workspace_id=_workspace_id(x_christina_workspace),
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Idea not found.")
    return item


@app.post("/api/ideas/{idea_id}/agent-documents", status_code=201)
async def generate_agent_documents_for_idea(
    idea_id: int,
    payload: IdeaAgentProductionDocsRequest,
    x_christina_workspace: str | None = Header(default=None, alias="X-Christina-Workspace"),
) -> dict:
    if not creator_agent_configured():
        raise HTTPException(
            status_code=503,
            detail="Creator Agent is not configured. Add a key for the selected AI provider.",
        )

    workspace_id = _workspace_id(x_christina_workspace)
    platform = payload.platform.strip()

    idea = snapshot_store.get_idea(idea_id, workspace_id=workspace_id)
    if idea is None:
        raise HTTPException(status_code=404, detail="Idea not found.")

    content_type = "Short" if str(idea.get("type") or "") == "Short" else "Long-form"
    if content_type == "Short":
        allowed_platforms = {
            "YouTube Shorts",
            "TikTok",
            "Pinterest",
            "Instagram",
        }
        if platform not in allowed_platforms:
            raise HTTPException(
                status_code=422,
                detail="For Short ideas, choose YouTube Shorts, TikTok, Pinterest, or Instagram.",
            )
        target_duration_minutes = None
    else:
        if platform != "YouTube":
            raise HTTPException(
                status_code=422,
                detail="Long-form ideas currently use YouTube as the production platform.",
            )
        if payload.targetDurationMinutes is None:
            raise HTTPException(
                status_code=422,
                detail="Choose a target video length for the long-form YouTube production pack.",
            )
        target_duration_minutes = payload.targetDurationMinutes

    source_research = None
    source_video_id = str(idea.get("sourceVideoId") or "").strip()
    if source_video_id:
        source_research = next(
            (
                item
                for item in snapshot_store.list_saved_research(workspace_id=workspace_id)
                if str(item.get("videoId") or item.get("id") or "") == source_video_id
            ),
            None,
        )

    try:
        generated = await generate_idea_production_docs(
            idea=idea,
            source_research=source_research,
            platform=platform,
            target_duration_minutes=target_duration_minutes,
        )
    except CreatorAgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    safe_platform = "-".join(
        part for part in re.sub(r"[^a-z0-9]+", "-", platform.lower()).split("-") if part
    ) or "platform"
    safe_duration = (
        f"-{target_duration_minutes}min"
        if target_duration_minutes is not None
        else ""
    )

    documents = []
    for kind, suffix, body in (
        ("script", "script", generated.get("script", "")),
        ("plan", "production-plan", generated.get("productionPlan", "")),
        ("video_prompt", "video-prompt", generated.get("videoPrompt", "")),
        ("photo_reference", "photo-reference", generated.get("photoReference", "")),
    ):
        text_body = str(body or "").strip()
        if not text_body:
            continue
        documents.append(
            snapshot_store.save_idea_document(
                idea_id,
                kind=kind,
                filename=f"idea-{idea_id}-{safe_platform}{safe_duration}-{suffix}.md",
                content_type="text/markdown; charset=utf-8",
                content=(text_body + "\n").encode("utf-8"),
                workspace_id=workspace_id,
            )
        )

    return {
        "ideaId": idea_id,
        "contentType": content_type,
        "platform": platform,
        "targetDurationMinutes": target_duration_minutes,
        "documents": documents,
        "provider": generated.get("_agentProvider") or creator_agent_provider(),
        "model": generated.get("_agentModel") or creator_agent_model(),
    }


@app.get("/api/ideas/{idea_id}/documents")
async def idea_documents(
    idea_id: int,
    x_christina_workspace: str | None = Header(default=None, alias="X-Christina-Workspace"),
) -> dict:
    try:
        items = snapshot_store.list_idea_documents(
            idea_id,
            workspace_id=_workspace_id(x_christina_workspace),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"count": len(items), "items": items}


@app.post("/api/ideas/{idea_id}/documents", status_code=201)
async def upload_idea_document(
    idea_id: int,
    payload: IdeaDocumentUpload,
    x_christina_workspace: str | None = Header(default=None, alias="X-Christina-Workspace"),
) -> dict:
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
            workspace_id=_workspace_id(x_christina_workspace),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/idea-documents/{document_id}")
async def download_idea_document(
    document_id: int,
    x_christina_workspace: str | None = Header(default=None, alias="X-Christina-Workspace"),
) -> Response:
    item = snapshot_store.get_idea_document(
        document_id,
        workspace_id=_workspace_id(x_christina_workspace),
    )
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
async def update_idea_document_cloud(
    document_id: int,
    payload: IdeaDocumentCloudUpdate,
    x_christina_workspace: str | None = Header(default=None, alias="X-Christina-Workspace"),
) -> dict:
    provider = payload.provider.strip().lower()
    if provider != "google_docs":
        raise HTTPException(status_code=422, detail="Unsupported cloud provider.")
    item = snapshot_store.update_idea_document_cloud(
        document_id,
        provider=provider,
        file_id=payload.fileId.strip(),
        url=payload.url.strip(),
        workspace_id=_workspace_id(x_christina_workspace),
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return item


@app.delete("/api/idea-documents/{document_id}")
async def delete_idea_document(
    document_id: int,
    x_christina_workspace: str | None = Header(default=None, alias="X-Christina-Workspace"),
) -> dict:
    return {
        "documentId": document_id,
        "deleted": snapshot_store.delete_idea_document(
            document_id,
            workspace_id=_workspace_id(x_christina_workspace),
        ),
    }


@app.post("/api/agent/research")
async def creator_agent_research(
    payload: CreatorAgentResearchRequest,
    x_christina_workspace: str | None = Header(default=None, alias="X-Christina-Workspace"),
) -> dict:
    if not creator_agent_configured():
        raise HTTPException(
            status_code=503,
            detail="Creator Agent is not configured. Add a key for the selected AI provider (Gemini is the default).",
        )

    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="YOUTUBE_API_KEY is not configured on the backend.",
        )

    search_query = (payload.topic or payload.project).strip()
    try:
        youtube = await YouTubeClient(api_key, snapshot_store=snapshot_store).discover(
            query=search_query,
            max_results=12,
            published_after_days=3650,
            mode="reference",
        )
    except YouTubeAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    repo_context = await load_github_repo_context(payload.repoUrl)
    saved = relevant_saved_research(
        snapshot_store.list_saved_research(
            workspace_id=_workspace_id(x_christina_workspace)
        ),
        project=payload.project,
        topic=payload.topic,
    )
    sources = compact_youtube_sources(youtube.get("videos", []), limit=10)

    try:
        result = await research_angles(
            project=payload.project.strip(),
            goal=payload.goal.strip(),
            topic=payload.topic.strip(),
            content_type=payload.contentType.strip() or "Long-form",
            repo_context=repo_context,
            youtube_sources=sources,
            saved_research=saved,
        )
    except CreatorAgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        **result,
        "project": payload.project.strip(),
        "goal": payload.goal.strip(),
        "topic": payload.topic.strip(),
        "contentType": payload.contentType.strip() or "Long-form",
        "youtubeCount": len(sources),
        "savedResearchCount": len(saved),
    }


@app.get("/api/agent/shorts/transcript/{video_id}")
async def creator_agent_short_transcript(video_id: str) -> dict:
    try:
        return await load_public_youtube_transcript(video_id)
    except CreatorAgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/agent/shorts/analyze")
async def creator_agent_short_analyze(payload: CreatorAgentShortAnalyzeRequest) -> dict:
    if not creator_agent_configured():
        raise HTTPException(
            status_code=503,
            detail="Creator Agent is not configured. Add a key for the selected AI provider.",
        )

    source = payload.source.model_dump()
    try:
        result = await analyze_short_transcript(
            source_title=str(source.get("title") or "Reference video").strip(),
            source_url=str(source.get("url") or "").strip(),
            transcript=payload.transcript.strip(),
            platform=payload.platform.strip() or "YouTube Shorts",
        )
    except CreatorAgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        **result,
        "source": source,
        "platform": payload.platform.strip() or "YouTube Shorts",
        "provider": result.get("_agentProvider") or creator_agent_provider(),
        "model": result.get("_agentModel") or creator_agent_model(),
    }


@app.post("/api/agent/shorts/generate")
async def creator_agent_short_generate(payload: CreatorAgentShortGenerateRequest) -> dict:
    if not creator_agent_configured():
        raise HTTPException(
            status_code=503,
            detail="Creator Agent is not configured. Add a key for the selected AI provider.",
        )

    source = payload.source.model_dump()
    moment = payload.moment.model_dump()
    try:
        result = await generate_short_package(
            source_title=str(source.get("title") or "Reference video").strip(),
            source_url=str(source.get("url") or "").strip(),
            transcript=payload.transcript.strip(),
            chosen_moment=moment,
            platform=payload.platform.strip() or "YouTube Shorts",
            duration_seconds=payload.durationSeconds,
            has_reference_frame=payload.hasReferenceFrame,
        )
    except CreatorAgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        **result,
        "source": source,
        "moment": moment,
        "platform": payload.platform.strip() or "YouTube Shorts",
        "durationSeconds": payload.durationSeconds,
        "provider": result.get("_agentProvider") or creator_agent_provider(),
        "model": result.get("_agentModel") or creator_agent_model(),
    }


@app.post("/api/agent/package", status_code=201)
async def creator_agent_package(
    payload: CreatorAgentPackageRequest,
    x_christina_workspace: str | None = Header(default=None, alias="X-Christina-Workspace"),
) -> dict:
    if not creator_agent_configured():
        raise HTTPException(
            status_code=503,
            detail="Creator Agent is not configured. Add a key for the selected AI provider (Gemini is the default).",
        )

    workspace_id = _workspace_id(x_christina_workspace)
    repo_context = await load_github_repo_context(payload.repoUrl)
    saved = relevant_saved_research(
        snapshot_store.list_saved_research(workspace_id=workspace_id),
        project=payload.project,
        topic=payload.topic,
    )
    source_materials = [item.model_dump() for item in payload.sourceMaterials]
    angle = payload.angle.model_dump()

    try:
        package = await generate_package(
            project=payload.project.strip(),
            goal=payload.goal.strip(),
            topic=payload.topic.strip(),
            content_type=payload.contentType.strip() or "Long-form",
            repo_context=repo_context,
            chosen_angle=angle,
            source_materials=source_materials,
            saved_research=saved,
        )
    except CreatorAgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    idea_payload = package.get("idea", {})
    idea = snapshot_store.create_idea(
        title=str(idea_payload.get("title") or payload.angle.title).strip(),
        source_video_id=None,
        hook=str(idea_payload.get("hook") or payload.angle.hook).strip(),
        topic=str(idea_payload.get("topic") or payload.topic or payload.project).strip(),
        content_type=str(idea_payload.get("contentType") or payload.contentType or "Long-form").strip(),
        angle=str(idea_payload.get("angle") or payload.angle.positioning).strip(),
        audience=str(idea_payload.get("audience") or "").strip(),
        hypothesis=str(idea_payload.get("hypothesis") or "").strip(),
        notes=str(idea_payload.get("notes") or "Generated by Christina Lab Creator Agent.").strip(),
        priority="Med",
        status="Draft",
        workspace_id=workspace_id,
    )

    safe_slug = "".join(
        char.lower() if char.isalnum() else "-"
        for char in str(idea.get("title") or "creator-package")
    )
    safe_slug = "-".join(part for part in safe_slug.split("-") if part)[:72] or "creator-package"

    docs = []
    for kind, suffix, body in (
        ("reference", "research-brief", package.get("researchBrief", "")),
        ("script", "script", package.get("script", "")),
        ("plan", "production-blueprint", package.get("productionBlueprint", "")),
    ):
        text_body = str(body or "").strip()
        if not text_body:
            continue
        docs.append(
            snapshot_store.save_idea_document(
                int(idea["id"]),
                kind=kind,
                filename=f"{safe_slug}-{suffix}.md",
                content_type="text/markdown; charset=utf-8",
                content=text_body.encode("utf-8"),
                workspace_id=workspace_id,
            )
        )

    render_manifest = package.get("renderManifest")
    if isinstance(render_manifest, dict):
        docs.append(
            snapshot_store.save_idea_document(
                int(idea["id"]),
                kind="plan",
                filename=f"{safe_slug}-render-manifest.json",
                content_type="application/json; charset=utf-8",
                content=(
                    json.dumps(render_manifest, ensure_ascii=False, indent=2) + "\n"
                ).encode("utf-8"),
                workspace_id=workspace_id,
            )
        )

    return {
        "idea": idea,
        "documents": docs,
        "thumbnailConcept": package.get("thumbnailConcept", ""),
        "description": package.get("description", ""),
        "cta": package.get("cta", ""),
        "renderManifest": package.get("renderManifest"),
        "videoBuilderReady": bool(package.get("renderManifest")),
        "provider": package.get("_agentProvider") or creator_agent_provider(),
        "model": package.get("_agentModel") or creator_agent_model(),
    }


@app.get("/api/experiments")
async def experiments(
    x_christina_workspace: str | None = Header(default=None, alias="X-Christina-Workspace"),
) -> dict:
    items = snapshot_store.list_experiments(
        workspace_id=_workspace_id(x_christina_workspace)
    )
    return {"count": len(items), "items": items}


@app.post("/api/experiments", status_code=201)
async def create_experiment(
    payload: ExperimentCreate,
    x_christina_workspace: str | None = Header(default=None, alias="X-Christina-Workspace"),
) -> dict:
    _validate_choice(payload.status, EXPERIMENT_STATUSES, "Experiment status")
    _validate_choice(payload.decision, EXPERIMENT_DECISIONS, "Decision")
    try:
        return snapshot_store.create_experiment(
            idea_id=payload.ideaId,
            name=payload.name,
            hypothesis=payload.hypothesis,
            status=payload.status,
            decision=payload.decision,
            workspace_id=_workspace_id(x_christina_workspace),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/experiments/{experiment_id}")
async def experiment(
    experiment_id: int,
    x_christina_workspace: str | None = Header(default=None, alias="X-Christina-Workspace"),
) -> dict:
    item = snapshot_store.get_experiment(
        experiment_id,
        workspace_id=_workspace_id(x_christina_workspace),
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Experiment not found.")
    return item


@app.patch("/api/experiments/{experiment_id}")
async def update_experiment(
    experiment_id: int,
    payload: ExperimentUpdate,
    x_christina_workspace: str | None = Header(default=None, alias="X-Christina-Workspace"),
) -> dict:
    changes = _model_changes(payload)
    _validate_choice(changes.get("status"), EXPERIMENT_STATUSES, "Experiment status")
    _validate_choice(changes.get("decision"), EXPERIMENT_DECISIONS, "Decision")
    item = snapshot_store.update_experiment(
        experiment_id,
        changes,
        workspace_id=_workspace_id(x_christina_workspace),
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Experiment not found.")
    return item


@app.delete("/api/experiments/{experiment_id}")
async def delete_experiment(
    experiment_id: int,
    x_christina_workspace: str | None = Header(default=None, alias="X-Christina-Workspace"),
) -> dict:
    deleted = snapshot_store.delete_experiment(
        experiment_id,
        workspace_id=_workspace_id(x_christina_workspace),
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Experiment not found.")
    return {"experimentId": experiment_id, "deleted": True}


# Serve the lightweight frontend from the same Render service for the alpha deployment.
@app.get("/", include_in_schema=False)
async def frontend_index():
    return FileResponse(
        os.path.join(FRONTEND_DIR, "index.html"),
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/{asset_name}", include_in_schema=False)
async def frontend_asset(asset_name: str):
    allowed_assets = {"styles.css", "data.js", "agent.js", "app.js", "thumb.jpg"}
    if asset_name not in allowed_assets:
        raise HTTPException(status_code=404, detail="Not found.")
    return FileResponse(
        os.path.join(FRONTEND_DIR, asset_name),
        headers={"Cache-Control": "no-store, max-age=0"},
    )

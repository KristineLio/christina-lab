from __future__ import annotations

import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .storage import SnapshotStore
from .youtube import YouTubeAPIError, YouTubeClient


load_dotenv()

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
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok",
        "youtubeConfigured": bool(os.getenv("YOUTUBE_API_KEY")),
        "snapshotStore": snapshot_store.stats(),
    }


@app.get("/api/discover")
async def discover(
    q: str = Query(..., min_length=2, max_length=120),
    max_results: int = Query(25, ge=1, le=50),
    published_after_days: int = Query(7, ge=1, le=30),
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

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Iterable


DEFAULT_DATABASE_URL = "sqlite:///./christina_lab.sqlite3"
SNAPSHOT_MIN_INTERVAL_MINUTES = 15


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class SnapshotStore:
    """Small SQLite persistence layer for public YouTube observations.

    Every time Christina Lab sees a video, it can record the video's public
    metrics at that moment. Over time these observations become true
    age-matched history instead of an estimate based on lifetime averages.
    """

    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or os.getenv("DATABASE_URL") or DEFAULT_DATABASE_URL
        self.path = self._sqlite_path(self.database_url)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    @staticmethod
    def _sqlite_path(database_url: str) -> str:
        value = (database_url or DEFAULT_DATABASE_URL).strip()
        if value == "sqlite:///:memory:":
            return ":memory:"
        prefix = "sqlite:///"
        if not value.startswith(prefix):
            raise ValueError("Milestone 4 currently supports SQLite DATABASE_URL values only.")
        path = value[len(prefix) :]
        return path or "./christina_lab.sqlite3"

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def init_schema(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS videos (
                    video_id TEXT PRIMARY KEY,
                    channel_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    live_status TEXT NOT NULL DEFAULT 'none',
                    duration_seconds INTEGER NOT NULL DEFAULT 0,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_videos_channel_type
                ON videos(channel_id, content_type, published_at);

                CREATE TABLE IF NOT EXISTS video_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    age_hours REAL NOT NULL,
                    views INTEGER NOT NULL,
                    likes INTEGER NOT NULL,
                    comments INTEGER NOT NULL,
                    subscribers INTEGER,
                    FOREIGN KEY(video_id) REFERENCES videos(video_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_snapshots_video_time
                ON video_snapshots(video_id, observed_at);

                CREATE INDEX IF NOT EXISTS idx_snapshots_video_age
                ON video_snapshots(video_id, age_hours);
                """
            )

    def record_snapshots(
        self,
        videos: Iterable[dict],
        *,
        observed_at: datetime | None = None,
        min_interval_minutes: int = SNAPSHOT_MIN_INTERVAL_MINUTES,
    ) -> int:
        observed_at = observed_at or _utc_now()
        observed_iso = _iso(observed_at)
        inserted = 0

        with self._connect() as db:
            for video in videos:
                video_id = str(video.get("id") or "")
                channel_id = str(video.get("channelId") or "")
                published_at = video.get("publishedAt")
                if not video_id or not channel_id or not isinstance(published_at, datetime):
                    continue

                published_iso = _iso(published_at)
                db.execute(
                    """
                    INSERT INTO videos (
                        video_id, channel_id, title, published_at, content_type,
                        live_status, duration_seconds, first_seen_at, last_seen_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(video_id) DO UPDATE SET
                        channel_id = excluded.channel_id,
                        title = excluded.title,
                        published_at = excluded.published_at,
                        content_type = excluded.content_type,
                        live_status = excluded.live_status,
                        duration_seconds = excluded.duration_seconds,
                        last_seen_at = excluded.last_seen_at
                    """,
                    (
                        video_id,
                        channel_id,
                        str(video.get("title") or "Untitled"),
                        published_iso,
                        str(video.get("type") or "Long-form"),
                        str(video.get("liveStatus") or "none"),
                        int(video.get("durationSeconds") or 0),
                        observed_iso,
                        observed_iso,
                    ),
                )

                latest = db.execute(
                    """
                    SELECT observed_at, views, likes, comments
                    FROM video_snapshots
                    WHERE video_id = ?
                    ORDER BY observed_at DESC
                    LIMIT 1
                    """,
                    (video_id,),
                ).fetchone()

                if latest:
                    latest_at = _parse_iso(latest["observed_at"])
                    if observed_at - latest_at < timedelta(minutes=min_interval_minutes):
                        continue

                age_hours = max((observed_at - published_at).total_seconds() / 3600, 0.0)
                db.execute(
                    """
                    INSERT INTO video_snapshots (
                        video_id, observed_at, age_hours, views, likes, comments, subscribers
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        video_id,
                        observed_iso,
                        round(age_hours, 4),
                        max(int(video.get("views") or 0), 0),
                        max(int(video.get("likes") or 0), 0),
                        max(int(video.get("comments") or 0), 0),
                        (
                            int(video["subscribers"])
                            if video.get("subscribers") is not None
                            else None
                        ),
                    ),
                )
                inserted += 1

        return inserted

    @staticmethod
    def age_tolerance_hours(target_age_hours: float) -> float:
        age = max(float(target_age_hours), 0.0)
        if age <= 2:
            return 1.0
        if age <= 8:
            return 2.0
        if age <= 16:
            return 3.0
        if age <= 36:
            return 6.0
        if age <= 72:
            return 12.0
        return min(max(age * 0.20, 12.0), 48.0)

    def same_age_baseline(
        self,
        *,
        channel_id: str,
        content_type: str,
        candidate_id: str,
        target_age_hours: float,
        min_samples: int = 3,
        max_samples: int = 12,
    ) -> dict:
        tolerance = self.age_tolerance_hours(target_age_hours)
        minimum_age = max(float(target_age_hours) - tolerance, 0.0)
        maximum_age = float(target_age_hours) + tolerance

        with self._connect() as db:
            rows = db.execute(
                """
                SELECT
                    s.video_id,
                    s.age_hours,
                    s.views,
                    s.likes,
                    s.comments,
                    s.observed_at,
                    v.published_at
                FROM video_snapshots s
                JOIN videos v ON v.video_id = s.video_id
                WHERE v.channel_id = ?
                  AND v.content_type = ?
                  AND v.video_id <> ?
                  AND s.age_hours BETWEEN ? AND ?
                  AND s.views > 0
                ORDER BY v.published_at DESC, s.video_id, ABS(s.age_hours - ?) ASC
                """,
                (
                    channel_id,
                    content_type,
                    candidate_id,
                    minimum_age,
                    maximum_age,
                    float(target_age_hours),
                ),
            ).fetchall()

        # Keep the closest snapshot to the candidate's age for each historical video.
        closest_by_video: dict[str, sqlite3.Row] = {}
        for row in rows:
            existing = closest_by_video.get(row["video_id"])
            if existing is None:
                closest_by_video[row["video_id"]] = row
                continue
            old_distance = abs(float(existing["age_hours"]) - float(target_age_hours))
            new_distance = abs(float(row["age_hours"]) - float(target_age_hours))
            if new_distance < old_distance:
                closest_by_video[row["video_id"]] = row

        chosen = list(closest_by_video.values())[:max_samples]
        if len(chosen) < min_samples:
            return {
                "ready": False,
                "baseline": None,
                "sampleSize": len(chosen),
                "targetAgeHours": round(float(target_age_hours), 2),
                "toleranceHours": round(tolerance, 2),
                "method": "historical-snapshot-median",
            }

        baseline = float(median(int(row["views"]) for row in chosen))
        return {
            "ready": baseline > 0,
            "baseline": int(round(baseline)) if baseline > 0 else None,
            "sampleSize": len(chosen),
            "targetAgeHours": round(float(target_age_hours), 2),
            "toleranceHours": round(tolerance, 2),
            "method": "historical-snapshot-median",
            "samples": [
                {
                    "videoId": row["video_id"],
                    "ageHours": round(float(row["age_hours"]), 2),
                    "views": int(row["views"]),
                    "observedAt": row["observed_at"],
                }
                for row in chosen
            ],
        }

    def video_snapshots(self, video_id: str, *, limit: int = 50) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT observed_at, age_hours, views, likes, comments, subscribers
                FROM video_snapshots
                WHERE video_id = ?
                ORDER BY observed_at ASC
                LIMIT ?
                """,
                (video_id, max(1, min(int(limit), 500))),
            ).fetchall()

        return [
            {
                "observedAt": row["observed_at"],
                "ageHours": round(float(row["age_hours"]), 2),
                "views": int(row["views"]),
                "likes": int(row["likes"]),
                "comments": int(row["comments"]),
                "subscribers": (
                    int(row["subscribers"]) if row["subscribers"] is not None else None
                ),
            }
            for row in rows
        ]

    def stats(self) -> dict:
        with self._connect() as db:
            video_count = int(db.execute("SELECT COUNT(*) FROM videos").fetchone()[0])
            snapshot_count = int(
                db.execute("SELECT COUNT(*) FROM video_snapshots").fetchone()[0]
            )
            multi_snapshot_videos = int(
                db.execute(
                    """
                    SELECT COUNT(*)
                    FROM (
                        SELECT video_id
                        FROM video_snapshots
                        GROUP BY video_id
                        HAVING COUNT(*) >= 2
                    )
                    """
                ).fetchone()[0]
            )

        return {
            "videosTracked": video_count,
            "snapshotsStored": snapshot_count,
            "videosWithMultipleSnapshots": multi_snapshot_videos,
        }

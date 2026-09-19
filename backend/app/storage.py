from __future__ import annotations

import os
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Iterable


DEFAULT_DATABASE_URL = "sqlite:///./christina_lab.sqlite3"
SNAPSHOT_MIN_INTERVAL_MINUTES = 15

_TITLE_STOPWORDS = {
    "about", "after", "again", "against", "also", "been", "before", "being",
    "best", "for", "from", "have", "how", "into", "just", "latest", "more",
    "most", "new", "our", "over", "real", "september", "that", "the",
    "their", "them", "then", "there", "these", "they", "this", "those",
    "today", "top", "video", "what", "when", "where", "which", "while",
    "with", "your", "you", "why", "2026",
}

# Common YouTube/SEO tokens that create noisy "patterns" but rarely describe
# the content idea itself. Hashtag forms are stripped before tokenization too.
_TITLE_SEO_NOISE = {
    "dubai", "explore", "foryou", "foryoupage", "fyp", "india", "london",
    "reels", "short", "shorts", "shortsfeed", "singapore", "subscribe",
    "trending", "uk", "usa", "viral", "youtube", "youtubeshorts", "ytshorts",
}

# These words can be useful inside phrases ("copy trading", "trading journal")
# but are too broad to surface as meaningful one-word title patterns.
_TITLE_GENERIC_SINGLETONS = {
    "bitcoin", "btc", "crypto", "cryptocurrency", "day", "gold", "live",
    "market", "markets", "motivation", "news", "setup", "stock", "stockmarket",
    "strategy", "trade", "trader", "traders", "trading", "update",
}

_TITLE_NORMALIZATIONS = {
    "aitools": ("ai", "tools"),
    "artificialintelligence": ("artificial", "intelligence"),
    "copytrading": ("copy", "trading"),
    "daytrading": ("day", "trading"),
    "stockmarket": ("stock", "market"),
    "tradingjournal": ("trading", "journal"),
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _median(values: list[float | int]) -> float:
    return float(median(values)) if values else 0.0


def _percentile(values: list[float | int], percentile: float) -> float:
    """Linear percentile that behaves sensibly for small local datasets."""
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = max(0.0, min(float(percentile), 1.0)) * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _title_terms(title: str) -> set[str]:
    """Extract literal but higher-signal title words/phrases.

    We remove generic YouTube hashtag/SEO noise, keep domain words available
    for phrases, and suppress broad one-word terms such as "trading".
    """
    text = (title or "").lower()

    # Remove noisy hashtags as whole units before punctuation is discarded.
    text = re.sub(
        r"#(?:explore|foryou|foryoupage|fyp|reels|shorts?|shortsfeed|subscribe|"
        r"trending|viral|youtube|youtubeshorts|ytshorts)\\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )

    raw_tokens = re.findall(r"[a-z0-9]+", text)
    tokens: list[str] = []
    for raw_token in raw_tokens:
        expanded = _TITLE_NORMALIZATIONS.get(raw_token, (raw_token,))
        for token in expanded:
            if (
                (len(token) >= 3 or token == "ai")
                and token not in _TITLE_STOPWORDS
                and token not in _TITLE_SEO_NOISE
                and not token.isdigit()
            ):
                tokens.append(token)

    terms = {
        token
        for token in tokens
        if token not in _TITLE_GENERIC_SINGLETONS
    }

    for first, second in zip(tokens, tokens[1:]):
        if first == second:
            continue
        # Avoid phrases made entirely from generic category words such as
        # "crypto trading", while preserving "copy trading" / "trading journal".
        if first in _TITLE_GENERIC_SINGLETONS and second in _TITLE_GENERIC_SINGLETONS:
            continue
        terms.add(f"{first} {second}")

    return terms


class SnapshotStore:
    """SQLite persistence for YouTube observations and derived research signals."""

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
            raise ValueError("Christina Lab currently supports SQLite DATABASE_URL values only.")
        path = value[len(prefix) :]
        return path or "./christina_lab.sqlite3"

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _columns(db: sqlite3.Connection, table: str) -> set[str]:
        return {row["name"] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}

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

                CREATE TABLE IF NOT EXISTS video_analyses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    topic TEXT NOT NULL DEFAULT '',
                    opportunity INTEGER,
                    outlier REAL,
                    baseline INTEGER,
                    baseline_method TEXT NOT NULL DEFAULT '',
                    baseline_sample_size INTEGER NOT NULL DEFAULT 0,
                    views_day REAL NOT NULL DEFAULT 0,
                    engagement REAL NOT NULL DEFAULT 0,
                    views_sub REAL,
                    FOREIGN KEY(video_id) REFERENCES videos(video_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_analyses_video_time
                ON video_analyses(video_id, observed_at);

                CREATE INDEX IF NOT EXISTS idx_analyses_topic
                ON video_analyses(topic, observed_at);
                """
            )

            # Lightweight migrations for databases created by Milestone 4.
            video_columns = self._columns(db, "videos")
            if "channel_title" not in video_columns:
                db.execute("ALTER TABLE videos ADD COLUMN channel_title TEXT NOT NULL DEFAULT ''")
            if "thumbnail" not in video_columns:
                db.execute("ALTER TABLE videos ADD COLUMN thumbnail TEXT")
            if "youtube_url" not in video_columns:
                db.execute("ALTER TABLE videos ADD COLUMN youtube_url TEXT")

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
                        video_id, channel_id, channel_title, title, published_at,
                        content_type, live_status, duration_seconds, thumbnail,
                        youtube_url, first_seen_at, last_seen_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(video_id) DO UPDATE SET
                        channel_id = excluded.channel_id,
                        channel_title = CASE
                            WHEN excluded.channel_title <> '' THEN excluded.channel_title
                            ELSE videos.channel_title
                        END,
                        title = excluded.title,
                        published_at = excluded.published_at,
                        content_type = excluded.content_type,
                        live_status = excluded.live_status,
                        duration_seconds = excluded.duration_seconds,
                        thumbnail = COALESCE(excluded.thumbnail, videos.thumbnail),
                        youtube_url = COALESCE(excluded.youtube_url, videos.youtube_url),
                        last_seen_at = excluded.last_seen_at
                    """,
                    (
                        video_id,
                        channel_id,
                        str(video.get("channel") or video.get("channelTitle") or ""),
                        str(video.get("title") or "Untitled"),
                        published_iso,
                        str(video.get("type") or "Long-form"),
                        str(video.get("liveStatus") or "none"),
                        int(video.get("durationSeconds") or 0),
                        video.get("thumbnail"),
                        video.get("youtubeUrl")
                        or f"https://www.youtube.com/watch?v={video_id}",
                        observed_iso,
                        observed_iso,
                    ),
                )

                latest = db.execute(
                    """
                    SELECT observed_at
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
                        int(video["subscribers"]) if video.get("subscribers") is not None else None,
                    ),
                )
                inserted += 1

        return inserted

    def record_analyses(
        self,
        videos: Iterable[dict],
        *,
        topic: str,
        observed_at: datetime | None = None,
    ) -> int:
        """Persist derived candidate-level research signals from a Discover search."""
        observed_at = observed_at or _utc_now()
        observed_iso = _iso(observed_at)
        inserted = 0

        with self._connect() as db:
            for video in videos:
                video_id = str(video.get("id") or "")
                if not video_id:
                    continue
                exists = db.execute(
                    "SELECT 1 FROM videos WHERE video_id = ?",
                    (video_id,),
                ).fetchone()
                if not exists:
                    continue

                db.execute(
                    """
                    INSERT INTO video_analyses (
                        video_id, observed_at, topic, opportunity, outlier, baseline,
                        baseline_method, baseline_sample_size, views_day, engagement, views_sub
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        video_id,
                        observed_iso,
                        str(topic or "").strip(),
                        int(video["opportunity"]) if video.get("opportunity") is not None else None,
                        float(video["outlier"]) if video.get("outlier") is not None else None,
                        int(video["baseline"]) if video.get("baseline") is not None else None,
                        str(video.get("baselineMethod") or ""),
                        int(video.get("baselineSampleSize") or 0),
                        float(video.get("viewsDay") or 0),
                        float(video.get("engagement") or 0),
                        float(video["viewsSub"]) if video.get("viewsSub") is not None else None,
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
                "subscribers": int(row["subscribers"]) if row["subscribers"] is not None else None,
            }
            for row in rows
        ]

    def _latest_analysis_rows(self) -> list[sqlite3.Row]:
        with self._connect() as db:
            return db.execute(
                """
                SELECT
                    a.*,
                    v.title,
                    v.channel_id,
                    v.channel_title,
                    v.content_type,
                    v.thumbnail,
                    v.youtube_url,
                    v.published_at,
                    v.last_seen_at,
                    s.views,
                    s.likes,
                    s.comments,
                    s.age_hours
                FROM video_analyses a
                JOIN (
                    SELECT video_id, MAX(id) AS id
                    FROM video_analyses
                    GROUP BY video_id
                ) latest ON latest.id = a.id
                JOIN videos v ON v.video_id = a.video_id
                LEFT JOIN video_snapshots s ON s.id = (
                    SELECT s2.id
                    FROM video_snapshots s2
                    WHERE s2.video_id = a.video_id
                    ORDER BY s2.observed_at DESC
                    LIMIT 1
                )
                """
            ).fetchall()

    def _growth_rows(self) -> list[dict]:
        with self._connect() as db:
            videos = db.execute(
                """
                SELECT
                    v.video_id,
                    v.title,
                    v.channel_title,
                    v.content_type,
                    v.thumbnail,
                    COUNT(s.id) AS snapshot_count,
                    MIN(s.observed_at) AS first_observed,
                    MAX(s.observed_at) AS last_observed
                FROM videos v
                JOIN video_snapshots s ON s.video_id = v.video_id
                GROUP BY v.video_id
                HAVING COUNT(s.id) >= 2
                """
            ).fetchall()

            results = []
            for video in videos:
                first = db.execute(
                    """
                    SELECT observed_at, age_hours, views
                    FROM video_snapshots
                    WHERE video_id = ?
                    ORDER BY observed_at ASC
                    LIMIT 1
                    """,
                    (video["video_id"],),
                ).fetchone()
                last = db.execute(
                    """
                    SELECT observed_at, age_hours, views
                    FROM video_snapshots
                    WHERE video_id = ?
                    ORDER BY observed_at DESC
                    LIMIT 1
                    """,
                    (video["video_id"],),
                ).fetchone()
                if not first or not last:
                    continue
                span_hours = max(
                    (_parse_iso(last["observed_at"]) - _parse_iso(first["observed_at"])).total_seconds() / 3600,
                    0.001,
                )
                delta = int(last["views"]) - int(first["views"])
                results.append(
                    {
                        "id": video["video_id"],
                        "title": video["title"],
                        "channel": video["channel_title"] or video["video_id"],
                        "type": video["content_type"],
                        "thumbnail": video["thumbnail"],
                        "snapshotCount": int(video["snapshot_count"]),
                        "firstViews": int(first["views"]),
                        "latestViews": int(last["views"]),
                        "deltaViews": delta,
                        "spanHours": round(span_hours, 2),
                        "actualViewsHour": round(delta / span_hours, 2),
                        "growthPercent": (
                            round(delta / int(first["views"]) * 100, 1)
                            if int(first["views"]) > 0
                            else None
                        ),
                    }
                )
        return results

    def dashboard_summary(self) -> dict:
        stats = self.stats()
        analyses = self._latest_analysis_rows()
        growth = sorted(self._growth_rows(), key=lambda row: row["actualViewsHour"], reverse=True)

        top_opportunities = sorted(
            [row for row in analyses if row["opportunity"] is not None],
            key=lambda row: (int(row["opportunity"]), float(row["outlier"] or 0)),
            reverse=True,
        )[:5]

        with self._connect() as db:
            analyzed_candidates = int(
                db.execute("SELECT COUNT(DISTINCT video_id) FROM video_analyses").fetchone()[0]
            )
            topics_tracked = int(
                db.execute(
                    "SELECT COUNT(DISTINCT topic) FROM video_analyses WHERE TRIM(topic) <> ''"
                ).fetchone()[0]
            )
            historical_ready = int(
                db.execute(
                    """
                    SELECT COUNT(DISTINCT video_id)
                    FROM video_analyses
                    WHERE baseline_method = 'historical-snapshot-median'
                    """
                ).fetchone()[0]
            )
            content_rows = db.execute(
                """
                SELECT content_type, COUNT(*) AS count
                FROM videos
                GROUP BY content_type
                ORDER BY count DESC
                """
            ).fetchall()

        return {
            "generatedAt": _iso(_utc_now()),
            "metrics": {
                **stats,
                "analyzedCandidates": analyzed_candidates,
                "topicsTracked": topics_tracked,
                "historicalBaselinesReady": historical_ready,
            },
            "contentMix": [
                {"type": row["content_type"], "count": int(row["count"])}
                for row in content_rows
            ],
            "topOpportunities": [
                {
                    "id": row["video_id"],
                    "title": row["title"],
                    "channel": row["channel_title"] or row["channel_id"],
                    "type": row["content_type"],
                    "thumbnail": row["thumbnail"],
                    "youtubeUrl": row["youtube_url"],
                    "topic": row["topic"],
                    "views": int(row["views"] or 0),
                    "ageHours": round(float(row["age_hours"] or 0), 2),
                    "opportunity": int(row["opportunity"]),
                    "outlier": float(row["outlier"]) if row["outlier"] is not None else None,
                    "baseline": int(row["baseline"]) if row["baseline"] is not None else None,
                    "baselineMethod": row["baseline_method"],
                    "viewsDay": round(float(row["views_day"] or 0), 2),
                    "engagement": round(float(row["engagement"] or 0), 2),
                    "viewsSub": float(row["views_sub"]) if row["views_sub"] is not None else None,
                }
                for row in top_opportunities
            ],
            "fastestActualGrowth": growth[:5],
            "dataMaturity": {
                "historicalBaselinesReady": stats.get("historicalBaselinesReady", 0)
                if "historicalBaselinesReady" in stats
                else historical_ready,
                "videosWithMultipleSnapshots": stats["videosWithMultipleSnapshots"],
                "needsMoreHistory": max(stats["videosTracked"] - stats["videosWithMultipleSnapshots"], 0),
            },
        }

    def patterns_summary(self) -> dict:
        latest_analyses = self._latest_analysis_rows()
        growth_rows = self._growth_rows()

        # Search-topic patterns use the latest observation for each video/topic pair.
        with self._connect() as db:
            topic_rows = db.execute(
                """
                SELECT a.topic, a.video_id, a.opportunity, a.outlier
                FROM video_analyses a
                JOIN (
                    SELECT video_id, topic, MAX(id) AS id
                    FROM video_analyses
                    WHERE TRIM(topic) <> ''
                    GROUP BY video_id, topic
                ) latest ON latest.id = a.id
                """
            ).fetchall()

            video_rows = db.execute(
                """
                SELECT
                    v.video_id,
                    v.channel_id,
                    v.title,
                    v.content_type,
                    s.views,
                    s.likes,
                    s.comments
                FROM videos v
                LEFT JOIN video_snapshots s ON s.id = (
                    SELECT s2.id
                    FROM video_snapshots s2
                    WHERE s2.video_id = v.video_id
                    ORDER BY s2.observed_at DESC
                    LIMIT 1
                )
                """
            ).fetchall()

        topics: dict[str, dict] = {}
        for row in topic_rows:
            key = row["topic"].strip()
            bucket = topics.setdefault(key, {"videos": set(), "opportunity": [], "outlier": []})
            bucket["videos"].add(row["video_id"])
            if row["opportunity"] is not None:
                bucket["opportunity"].append(int(row["opportunity"]))
            if row["outlier"] is not None:
                bucket["outlier"].append(float(row["outlier"]))

        topic_patterns = []
        for topic, bucket in topics.items():
            topic_patterns.append(
                {
                    "topic": topic,
                    "videos": len(bucket["videos"]),
                    "avgOpportunity": round(sum(bucket["opportunity"]) / len(bucket["opportunity"]), 1)
                    if bucket["opportunity"]
                    else None,
                    "medianOutlier": round(_median(bucket["outlier"]), 2)
                    if bucket["outlier"]
                    else None,
                }
            )
        topic_patterns.sort(
            key=lambda row: (row["videos"], row["avgOpportunity"] or 0),
            reverse=True,
        )

        # Real content-type patterns from the latest stored public metrics.
        by_type: dict[str, dict] = defaultdict(lambda: {"videos": 0, "views": [], "engagement": []})
        for row in video_rows:
            bucket = by_type[row["content_type"]]
            bucket["videos"] += 1
            views = int(row["views"] or 0)
            bucket["views"].append(views)
            if views > 0:
                bucket["engagement"].append(
                    (int(row["likes"] or 0) + int(row["comments"] or 0)) / views * 100
                )

        growth_by_type: dict[str, list[float]] = defaultdict(list)
        for row in growth_rows:
            growth_by_type[row["type"]].append(float(row["actualViewsHour"]))

        content_patterns = []
        for content_type, bucket in by_type.items():
            growth_values = growth_by_type.get(content_type, [])
            positive_growth = [value for value in growth_values if value > 0]
            content_patterns.append(
                {
                    "type": content_type,
                    "videos": bucket["videos"],
                    "medianLatestViews": int(round(_median(bucket["views"]))),
                    "medianEngagement": round(_median(bucket["engagement"]), 2),
                    "medianActualGrowthPerHour": round(_median(growth_values), 2),
                    "topQuartileActualGrowthPerHour": round(
                        _percentile(growth_values, 0.75), 2
                    ),
                    "growthSampleSize": len(growth_values),
                    "positiveGrowthSampleSize": len(positive_growth),
                    "positiveGrowthShare": round(
                        len(positive_growth) / len(growth_values) * 100, 1
                    )
                    if growth_values
                    else None,
                }
            )
        content_patterns.sort(key=lambda row: row["videos"], reverse=True)

        latest_analysis_by_video = {row["video_id"]: row for row in latest_analyses}
        term_map: dict[str, dict] = defaultdict(
            lambda: {"videos": set(), "channels": set(), "opportunityByVideo": {}}
        )
        for row in video_rows:
            for term in _title_terms(row["title"]):
                bucket = term_map[term]
                bucket["videos"].add(row["video_id"])
                bucket["channels"].add(row["channel_id"])
                analysis = latest_analysis_by_video.get(row["video_id"])
                if analysis and analysis["opportunity"] is not None:
                    bucket["opportunityByVideo"][row["video_id"]] = int(
                        analysis["opportunity"]
                    )

        title_signals = []
        for term, bucket in term_map.items():
            video_count = len(bucket["videos"])
            channel_count = len(bucket["channels"])

            # A repeated phrase from one prolific channel is not yet a market
            # pattern. Require evidence across at least two independent channels.
            if video_count < 2 or channel_count < 2:
                continue

            opportunity_values = list(bucket["opportunityByVideo"].values())
            is_phrase = " " in term
            # Single words are only kept when they survive the stricter
            # stopword/generic filters above. Phrases are intentionally ranked
            # ahead of single words because they carry more creative meaning.
            title_signals.append(
                {
                    "term": term,
                    "termType": "phrase" if is_phrase else "specific-word",
                    "videos": video_count,
                    "channels": channel_count,
                    "avgOpportunity": round(
                        sum(opportunity_values) / len(opportunity_values), 1
                    )
                    if opportunity_values
                    else None,
                    "opportunitySampleSize": len(opportunity_values),
                }
            )
        title_signals.sort(
            key=lambda row: (
                1 if row["termType"] == "phrase" else 0,
                row["channels"],
                row["videos"],
                row["avgOpportunity"] or 0,
                len(row["term"]),
            ),
            reverse=True,
        )

        return {
            "generatedAt": _iso(_utc_now()),
            "dataset": {
                **self.stats(),
                "analyzedCandidates": len(latest_analyses),
                "growthPairs": len(growth_rows),
            },
            "topics": topic_patterns[:10],
            "contentTypes": content_patterns,
            "titleSignals": title_signals[:12],
            "actualGrowthLeaders": sorted(
                growth_rows,
                key=lambda row: row["actualViewsHour"],
                reverse=True,
            )[:8],
            "notes": {
                "topicPatterns": "Based on real Discover searches stored after Milestone 5.",
                "titleSignals": "Phrase-first, SEO-cleaned literal title signals repeated across at least two different channels; generic words and location noise are suppressed; no AI labeling.",
                "growthPatterns": "Uses only videos with at least two stored snapshots.",
            },
        }

    def stats(self) -> dict:
        with self._connect() as db:
            video_count = int(db.execute("SELECT COUNT(*) FROM videos").fetchone()[0])
            snapshot_count = int(db.execute("SELECT COUNT(*) FROM video_snapshots").fetchone()[0])
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

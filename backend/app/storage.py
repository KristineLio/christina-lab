from __future__ import annotations

import os
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Iterable

from .database import CompatRow, DatabaseBackend, DatabaseConnection
from .migrations import run_migrations


DEFAULT_DATABASE_URL = "sqlite:///./christina_lab.sqlite3"
SNAPSHOT_MIN_INTERVAL_MINUTES = 15

_TITLE_STOPWORDS = {
    "about", "after", "again", "against", "also", "been", "before", "being",
    "best", "for", "from", "have", "how", "into", "just", "latest", "like",
    "more", "most", "new", "our", "over", "real", "september", "that", "the",
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
    "action", "bitcoin", "btc", "comedy", "crypto", "cryptocurrency", "day",
    "funny", "gold", "live", "market", "markets", "motivation", "news",
    "setup", "stock", "stockmarket", "strategy", "trade", "trader", "traders",
    "trading", "update",
}

# Pairs made only from broad market/category words are usually just niche labels
# ("crypto trading", "bitcoin market") rather than reusable title patterns.
# Generic singleton words such as "gold" or "strategy" can still form useful
# phrases together ("gold strategy", "trading setup").
_TITLE_BROAD_CATEGORY_TERMS = {
    "bitcoin", "btc", "crypto", "cryptocurrency", "live", "market", "markets",
    "stock", "trade", "trader", "traders", "trading",
}

_TITLE_NORMALIZATIONS = {
    "aitools": ("ai", "tools"),
    "artificialintelligence": ("artificial", "intelligence"),
    "copytrading": ("copy", "trading"),
    "daytrading": ("day", "trading"),
    "stockmarket": ("stock", "market"),
    "tradingjournal": ("trading", "journal"),
}

# Deterministic phrase cleanup only. These are not AI interpretations:
# they normalize obvious word-order variants and remove filler bigrams that
# repeatedly appear because of surrounding sentence structure.
_TITLE_PHRASE_CANONICAL = {
    "trading forex": "forex trading",
}

_TITLE_PHRASE_BLOCKLIST = {
    "action trading",
    "funny comedy",
    "motivation trading",
    "trading like",
    "trading motivation",
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
        # Avoid phrases made entirely from broad category words such as
        # "crypto trading", while preserving useful combinations such as
        # "copy trading", "trading journal", "gold strategy", and "trading setup".
        if first in _TITLE_BROAD_CATEGORY_TERMS and second in _TITLE_BROAD_CATEGORY_TERMS:
            continue

        phrase = f"{first} {second}"
        phrase = _TITLE_PHRASE_CANONICAL.get(phrase, phrase)
        if phrase in _TITLE_PHRASE_BLOCKLIST:
            continue
        terms.add(phrase)

    return terms


class SnapshotStore:
    """Portable persistence for YouTube observations and creator workflow data."""

    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or os.getenv("DATABASE_URL") or DEFAULT_DATABASE_URL
        self._backend = DatabaseBackend(self.database_url)
        # Kept for backward compatibility with local tooling/tests that inspect
        # the SQLite path. PostgreSQL-backed stores expose None here.
        self.path = self._backend.sqlite_path
        self.init_schema()

    def _connect(self) -> DatabaseConnection:
        return self._backend.connect()

    def init_schema(self) -> None:
        run_migrations(self._connect)

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

        closest_by_video: dict[str, CompatRow] = {}
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

    def _latest_analysis_rows(self) -> list[CompatRow]:
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

        # Creative/title patterns must only use real Discover candidates.
        # The much larger videos table also contains channel-history uploads that
        # Christina Lab fetched only for baselines. Including those polluted
        # creative patterns with unrelated titles from a candidate's channel.
        term_map: dict[str, dict] = defaultdict(
            lambda: {"videos": set(), "channels": set(), "opportunityByVideo": {}}
        )
        for row in latest_analyses:
            for term in _title_terms(row["title"]):
                bucket = term_map[term]
                bucket["videos"].add(row["video_id"])
                bucket["channels"].add(row["channel_id"])
                if row["opportunity"] is not None:
                    bucket["opportunityByVideo"][row["video_id"]] = int(
                        row["opportunity"]
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
                "creativePatternCandidates": len(latest_analyses),
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
                "titleSignals": "Phrase-first, SEO-cleaned literal title signals from analyzed Discover candidates only; baseline-only channel-history uploads are excluded; signals must repeat across at least two different channels; no AI labeling.",
                "growthPatterns": "Uses only videos with at least two stored snapshots.",
            },
        }

    def _research_row(self, db: DatabaseConnection, video_id: str) -> CompatRow | None:
        return db.execute(
            """
            SELECT
                r.video_id,
                r.saved_at,
                r.updated_at,
                r.why_saved,
                r.adaptation,
                r.unique_angle,
                r.collection_name,
                v.title,
                v.channel_id,
                v.channel_title,
                v.content_type,
                v.live_status,
                v.thumbnail,
                v.youtube_url,
                s.views,
                s.likes,
                s.comments,
                s.subscribers,
                s.age_hours,
                a.topic,
                a.opportunity,
                a.outlier,
                a.baseline,
                a.baseline_method,
                a.views_day,
                a.engagement,
                a.views_sub,
                (
                    SELECT COUNT(*)
                    FROM ideas i
                    WHERE i.source_video_id = r.video_id
                ) AS idea_count
            FROM saved_research r
            JOIN videos v ON v.video_id = r.video_id
            LEFT JOIN video_snapshots s ON s.id = (
                SELECT s2.id
                FROM video_snapshots s2
                WHERE s2.video_id = r.video_id
                ORDER BY s2.observed_at DESC
                LIMIT 1
            )
            LEFT JOIN video_analyses a ON a.id = (
                SELECT a2.id
                FROM video_analyses a2
                WHERE a2.video_id = r.video_id
                ORDER BY a2.id DESC
                LIMIT 1
            )
            WHERE r.video_id = ?
            """,
            (video_id,),
        ).fetchone()

    @staticmethod
    def _serialize_research(row: CompatRow) -> dict:
        return {
            "id": row["video_id"],
            "videoId": row["video_id"],
            "savedAt": row["saved_at"],
            "updatedAt": row["updated_at"],
            "why": row["why_saved"],
            "adapt": row["adaptation"],
            "angle": row["unique_angle"],
            "collection": row["collection_name"],
            "title": row["title"],
            "channelId": row["channel_id"],
            "channel": row["channel_title"] or row["channel_id"],
            "type": row["content_type"],
            "liveStatus": row["live_status"],
            "thumbnail": row["thumbnail"],
            "youtubeUrl": row["youtube_url"],
            "views": int(row["views"] or 0),
            "likes": int(row["likes"] or 0),
            "comments": int(row["comments"] or 0),
            "subs": int(row["subscribers"]) if row["subscribers"] is not None else None,
            "ageHours": round(float(row["age_hours"] or 0), 2),
            "topic": row["topic"] or "",
            "opportunity": int(row["opportunity"]) if row["opportunity"] is not None else None,
            "outlier": float(row["outlier"]) if row["outlier"] is not None else None,
            "baseline": int(row["baseline"]) if row["baseline"] is not None else None,
            "baselineMethod": row["baseline_method"] or "",
            "viewsDay": round(float(row["views_day"] or 0), 2),
            "engagement": round(float(row["engagement"] or 0), 2),
            "viewsSub": float(row["views_sub"]) if row["views_sub"] is not None else None,
            "ideaCount": int(row["idea_count"] or 0),
        }

    def save_research(
        self,
        video_id: str,
        *,
        why: str | None = None,
        adapt: str | None = None,
        angle: str | None = None,
        collection: str | None = None,
    ) -> dict:
        now = _iso(_utc_now())
        with self._connect() as db:
            exists = db.execute(
                "SELECT 1 FROM videos WHERE video_id = ?",
                (video_id,),
            ).fetchone()
            if not exists:
                raise ValueError("Video is not in Christina Lab's research database yet.")

            current = db.execute(
                "SELECT * FROM saved_research WHERE video_id = ?",
                (video_id,),
            ).fetchone()

            if current is None:
                db.execute(
                    """
                    INSERT INTO saved_research (
                        video_id, saved_at, updated_at, why_saved, adaptation,
                        unique_angle, collection_name
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        video_id,
                        now,
                        now,
                        why or "",
                        adapt or "",
                        angle or "",
                        collection or "General",
                    ),
                )
            else:
                db.execute(
                    """
                    UPDATE saved_research
                    SET updated_at = ?,
                        why_saved = ?,
                        adaptation = ?,
                        unique_angle = ?,
                        collection_name = ?
                    WHERE video_id = ?
                    """,
                    (
                        now,
                        current["why_saved"] if why is None else why,
                        current["adaptation"] if adapt is None else adapt,
                        current["unique_angle"] if angle is None else angle,
                        current["collection_name"] if collection is None else collection,
                        video_id,
                    ),
                )

            row = self._research_row(db, video_id)
            if row is None:
                raise ValueError("Could not load saved research after saving.")
            return self._serialize_research(row)

    def remove_saved_research(self, video_id: str) -> bool:
        with self._connect() as db:
            cursor = db.execute(
                "DELETE FROM saved_research WHERE video_id = ?",
                (video_id,),
            )
            return cursor.rowcount > 0

    def list_saved_research(self) -> list[dict]:
        with self._connect() as db:
            ids = [
                row["video_id"]
                for row in db.execute(
                    "SELECT video_id FROM saved_research ORDER BY saved_at DESC"
                ).fetchall()
            ]
            rows = [self._research_row(db, video_id) for video_id in ids]
        return [self._serialize_research(row) for row in rows if row is not None]

    @staticmethod
    def _serialize_idea(row: CompatRow) -> dict:
        keys = set(row.keys())
        return {
            "id": int(row["id"]),
            "sourceVideoId": row["source_video_id"],
            "title": row["title"],
            "hook": row["hook"],
            "topic": row["topic"],
            "type": row["content_type"],
            "angle": row["angle"],
            "audience": row["audience"],
            "hypothesis": row["hypothesis"],
            "notes": row["notes"],
            "priority": row["priority"],
            "status": row["status"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "sources": 1 if row["source_video_id"] else 0,
            "documentCount": int(row["document_count"] or 0) if "document_count" in keys else 0,
        }

    @staticmethod
    def _serialize_idea_document(row: CompatRow, *, include_content: bool = False) -> dict:
        keys = set(row.keys())
        item = {
            "id": int(row["id"]),
            "ideaId": int(row["idea_id"]),
            "kind": row["kind"],
            "filename": row["filename"],
            "contentType": row["content_type"],
            "sizeBytes": int(row["size_bytes"] or 0),
            "uploadedAt": row["uploaded_at"],
            "cloudProvider": row["cloud_provider"] if "cloud_provider" in keys else "",
            "cloudFileId": row["cloud_file_id"] if "cloud_file_id" in keys else "",
            "cloudUrl": row["cloud_url"] if "cloud_url" in keys else "",
            "cloudUploadedAt": row["cloud_uploaded_at"] if "cloud_uploaded_at" in keys else None,
        }
        if include_content:
            item["content"] = bytes(row["content"])
        return item

    def _idea_row(self, db: DatabaseConnection, idea_id: int) -> CompatRow | None:
        return db.execute(
            """
            SELECT
                i.*,
                (
                    SELECT COUNT(*)
                    FROM idea_documents d
                    WHERE d.idea_id = i.id
                ) AS document_count
            FROM ideas i
            WHERE i.id = ?
            """,
            (idea_id,),
        ).fetchone()

    def create_idea(
        self,
        *,
        title: str,
        source_video_id: str | None = None,
        hook: str = "",
        topic: str = "",
        content_type: str = "Long-form",
        angle: str = "",
        audience: str = "",
        hypothesis: str = "",
        notes: str = "",
        priority: str = "Med",
        status: str = "Draft",
    ) -> dict:
        now = _iso(_utc_now())
        clean_title = str(title or "").strip()
        if not clean_title:
            raise ValueError("Idea title is required.")

        with self._connect() as db:
            if source_video_id:
                exists = db.execute(
                    "SELECT 1 FROM videos WHERE video_id = ?",
                    (source_video_id,),
                ).fetchone()
                if not exists:
                    raise ValueError("Source video is not in Christina Lab's research database.")

            cursor = db.execute(
                """
                INSERT INTO ideas (
                    source_video_id, title, hook, topic, content_type, angle,
                    audience, hypothesis, notes, priority, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_video_id,
                    clean_title,
                    hook,
                    topic,
                    content_type,
                    angle,
                    audience,
                    hypothesis,
                    notes,
                    priority,
                    status,
                    now,
                    now,
                ),
            )
            row = self._idea_row(db, int(cursor.lastrowid))
            return self._serialize_idea(row)

    def list_ideas(self) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT
                    i.*,
                    (
                        SELECT COUNT(*)
                        FROM idea_documents d
                        WHERE d.idea_id = i.id
                    ) AS document_count
                FROM ideas i
                ORDER BY i.updated_at DESC, i.id DESC
                """
            ).fetchall()
        return [self._serialize_idea(row) for row in rows]

    def get_idea(self, idea_id: int) -> dict | None:
        with self._connect() as db:
            row = self._idea_row(db, idea_id)
        return self._serialize_idea(row) if row else None

    def update_idea(self, idea_id: int, changes: dict) -> dict | None:
        allowed = {
            "title": "title",
            "hook": "hook",
            "topic": "topic",
            "contentType": "content_type",
            "angle": "angle",
            "audience": "audience",
            "hypothesis": "hypothesis",
            "notes": "notes",
            "priority": "priority",
            "status": "status",
        }
        updates = []
        values = []
        for key, column in allowed.items():
            if key in changes and changes[key] is not None:
                updates.append(f"{column} = ?")
                values.append(changes[key])

        if not updates:
            return self.get_idea(idea_id)

        updates.append("updated_at = ?")
        values.append(_iso(_utc_now()))
        values.append(idea_id)

        with self._connect() as db:
            cursor = db.execute(
                f"UPDATE ideas SET {', '.join(updates)} WHERE id = ?",
                values,
            )
            if cursor.rowcount == 0:
                return None
            row = self._idea_row(db, idea_id)
            return self._serialize_idea(row)

    def save_idea_document(
        self,
        idea_id: int,
        *,
        kind: str,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> dict:
        now = _iso(_utc_now())
        payload = bytes(content)
        with self._connect() as db:
            if self._idea_row(db, idea_id) is None:
                raise ValueError("Idea not found.")
            cursor = db.execute(
                """
                INSERT INTO idea_documents (
                    idea_id, kind, filename, content_type, size_bytes, content, uploaded_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    idea_id,
                    kind,
                    filename,
                    content_type,
                    len(payload),
                    payload,
                    now,
                ),
            )
            row = db.execute(
                "SELECT * FROM idea_documents WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
            return self._serialize_idea_document(row)

    def list_idea_documents(self, idea_id: int) -> list[dict]:
        with self._connect() as db:
            if self._idea_row(db, idea_id) is None:
                raise ValueError("Idea not found.")
            rows = db.execute(
                """
                SELECT
                    id, idea_id, kind, filename, content_type, size_bytes, uploaded_at,
                    cloud_provider, cloud_file_id, cloud_url, cloud_uploaded_at
                FROM idea_documents
                WHERE idea_id = ?
                ORDER BY uploaded_at DESC, id DESC
                """,
                (idea_id,),
            ).fetchall()
        return [self._serialize_idea_document(row) for row in rows]

    def get_idea_document(self, document_id: int) -> dict | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM idea_documents WHERE id = ?",
                (document_id,),
            ).fetchone()
        return self._serialize_idea_document(row, include_content=True) if row else None

    def update_idea_document_cloud(
        self,
        document_id: int,
        *,
        provider: str,
        file_id: str,
        url: str,
    ) -> dict | None:
        uploaded_at = _iso(_utc_now())
        with self._connect() as db:
            cursor = db.execute(
                """
                UPDATE idea_documents
                SET cloud_provider = ?,
                    cloud_file_id = ?,
                    cloud_url = ?,
                    cloud_uploaded_at = ?
                WHERE id = ?
                """,
                (provider, file_id, url, uploaded_at, document_id),
            )
            if cursor.rowcount == 0:
                return None
            row = db.execute(
                "SELECT * FROM idea_documents WHERE id = ?",
                (document_id,),
            ).fetchone()
            return self._serialize_idea_document(row)

    def delete_idea_document(self, document_id: int) -> bool:
        with self._connect() as db:
            cursor = db.execute(
                "DELETE FROM idea_documents WHERE id = ?",
                (document_id,),
            )
            return cursor.rowcount > 0

    @staticmethod
    def _serialize_experiment(row: CompatRow) -> dict:
        return {
            "id": int(row["id"]),
            "ideaId": int(row["idea_id"]),
            "name": row["name"],
            "topic": row["topic"],
            "format": row["format"],
            "hypothesis": row["hypothesis"],
            "status": row["status"],
            "publishedAt": row["published_at"],
            "v24": int(row["views_24h"]) if row["views_24h"] is not None else None,
            "v7": int(row["views_7d"]) if row["views_7d"] is not None else None,
            "retention": float(row["retention"]) if row["retention"] is not None else None,
            "subs": int(row["subscribers"]) if row["subscribers"] is not None else None,
            "ctr": float(row["ctr"]) if row["ctr"] is not None else None,
            "result": row["result"],
            "decision": row["decision"],
            "lesson": row["lesson"],
            "next": row["next_test"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    def create_experiment(
        self,
        *,
        idea_id: int,
        name: str | None = None,
        hypothesis: str | None = None,
        status: str | None = None,
        decision: str = "UNDECIDED",
    ) -> dict:
        now = _iso(_utc_now())
        with self._connect() as db:
            idea = db.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,)).fetchone()
            if idea is None:
                raise ValueError("Idea not found.")

            inherited_status = status or (
                idea["status"] if idea["status"] in {"Draft", "Ready", "Published"} else "Draft"
            )

            cursor = db.execute(
                """
                INSERT INTO experiments (
                    idea_id, name, topic, format, hypothesis, status, decision,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    idea_id,
                    (name or idea["title"]).strip(),
                    idea["topic"],
                    idea["content_type"],
                    hypothesis if hypothesis is not None else idea["hypothesis"],
                    inherited_status,
                    decision,
                    now,
                    now,
                ),
            )
            row = db.execute(
                "SELECT * FROM experiments WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
            return self._serialize_experiment(row)

    def list_experiments(self) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM experiments ORDER BY updated_at DESC, id DESC"
            ).fetchall()
        return [self._serialize_experiment(row) for row in rows]

    def get_experiment(self, experiment_id: int) -> dict | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM experiments WHERE id = ?",
                (experiment_id,),
            ).fetchone()
        return self._serialize_experiment(row) if row else None

    def update_experiment(self, experiment_id: int, changes: dict) -> dict | None:
        allowed = {
            "name": "name",
            "topic": "topic",
            "format": "format",
            "hypothesis": "hypothesis",
            "status": "status",
            "publishedAt": "published_at",
            "v24": "views_24h",
            "v7": "views_7d",
            "retention": "retention",
            "subs": "subscribers",
            "ctr": "ctr",
            "result": "result",
            "decision": "decision",
            "lesson": "lesson",
            "next": "next_test",
        }
        updates = []
        values = []
        for key, column in allowed.items():
            if key in changes:
                updates.append(f"{column} = ?")
                values.append(changes[key])

        if not updates:
            return self.get_experiment(experiment_id)

        updates.append("updated_at = ?")
        values.append(_iso(_utc_now()))
        values.append(experiment_id)

        with self._connect() as db:
            cursor = db.execute(
                f"UPDATE experiments SET {', '.join(updates)} WHERE id = ?",
                values,
            )
            if cursor.rowcount == 0:
                return None

            row = db.execute(
                "SELECT * FROM experiments WHERE id = ?",
                (experiment_id,),
            ).fetchone()
            if row["status"] == "Published":
                db.execute(
                    """
                    UPDATE ideas
                    SET status = 'Published', updated_at = ?
                    WHERE id = ?
                    """,
                    (_iso(_utc_now()), row["idea_id"]),
                )
            return self._serialize_experiment(row)

    def workflow_summary(self) -> dict:
        saved = self.list_saved_research()
        ideas = self.list_ideas()
        experiments = self.list_experiments()

        decision_counts = {"GO": 0, "TEST": 0, "HOLD": 0, "UNDECIDED": 0}
        for experiment in experiments:
            decision = experiment["decision"]
            decision_counts[decision] = decision_counts.get(decision, 0) + 1

        measured_v24 = [e["v24"] for e in experiments if e["v24"] is not None]
        measured_subs = [e["subs"] for e in experiments if e["subs"] is not None]

        by_topic: dict[str, dict] = {}
        for experiment in experiments:
            topic = (experiment["topic"] or "Unspecified").strip() or "Unspecified"
            bucket = by_topic.setdefault(
                topic,
                {
                    "topic": topic,
                    "experiments": 0,
                    "GO": 0,
                    "TEST": 0,
                    "HOLD": 0,
                    "UNDECIDED": 0,
                    "views24": [],
                    "subscribers": [],
                },
            )
            bucket["experiments"] += 1
            decision = experiment["decision"]
            bucket[decision] = bucket.get(decision, 0) + 1
            if experiment["v24"] is not None:
                bucket["views24"].append(experiment["v24"])
            if experiment["subs"] is not None:
                bucket["subscribers"].append(experiment["subs"])

        learning_signals = []
        for bucket in by_topic.values():
            views = bucket.pop("views24")
            subscribers = bucket.pop("subscribers")
            bucket["avg24hViews"] = (
                round(sum(views) / len(views)) if views else None
            )
            bucket["avgSubscriberGain"] = (
                round(sum(subscribers) / len(subscribers), 1) if subscribers else None
            )
            learning_signals.append(bucket)

        learning_signals.sort(
            key=lambda row: (
                row["experiments"],
                row["GO"],
                row["avg24hViews"] or 0,
            ),
            reverse=True,
        )

        return {
            "savedResearch": saved,
            "ideas": ideas,
            "experiments": experiments,
            "summary": {
                "savedResearch": len(saved),
                "ideas": len(ideas),
                "experiments": len(experiments),
                "publishedExperiments": sum(
                    1 for experiment in experiments if experiment["status"] == "Published"
                ),
                "decisions": decision_counts,
                "average24hViews": (
                    round(sum(measured_v24) / len(measured_v24))
                    if measured_v24
                    else None
                ),
                "averageSubscriberGain": (
                    round(sum(measured_subs) / len(measured_subs), 1)
                    if measured_subs
                    else None
                ),
            },
            "learningSignals": learning_signals,
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

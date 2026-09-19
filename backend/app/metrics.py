from __future__ import annotations

import re
from statistics import median
from datetime import datetime, timezone


_ISO_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)


def parse_youtube_duration(value: str) -> int:
    """Convert a YouTube ISO-8601 duration such as PT12M18S to seconds."""
    match = _ISO_DURATION_RE.match(value or "")
    if not match:
        return 0
    parts = {name: int(number or 0) for name, number in match.groupdict().items()}
    return (
        parts["days"] * 86400
        + parts["hours"] * 3600
        + parts["minutes"] * 60
        + parts["seconds"]
    )


def format_duration(total_seconds: int) -> str:
    total_seconds = max(int(total_seconds or 0), 0)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def human_age(published_at: datetime, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    hours = max((now - published_at).total_seconds() / 3600, 0)
    if hours < 1:
        return "<1h"
    if hours < 24:
        return f"{int(hours)}h"
    days = hours / 24
    if days < 30:
        rounded = int(days)
        return f"{rounded}d"
    months = int(days / 30)
    return f"{months}mo"


def calculate_video_metrics(
    *,
    views: int,
    likes: int,
    comments: int,
    subscribers: int | None,
    published_at: datetime,
    now: datetime | None = None,
) -> dict[str, float | None]:
    now = now or datetime.now(timezone.utc)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)

    age_hours = max((now - published_at).total_seconds() / 3600, 1.0)
    views_hour = views / age_hours
    views_day = views / max(age_hours / 24, 1 / 24)
    engagement = ((likes + comments) / views * 100) if views > 0 else 0.0
    views_sub = (views / subscribers) if subscribers and subscribers > 0 else None

    return {
        "viewsHour": round(views_hour, 2),
        "viewsDay": round(views_day, 2),
        "engagement": round(engagement, 2),
        "viewsSub": round(views_sub, 4) if views_sub is not None else None,
    }


def calculate_channel_baseline(
    *,
    candidate_id: str,
    candidate_views: int,
    candidate_type: str,
    samples: list[dict],
    min_samples: int = 3,
) -> dict[str, int | float | str | None]:
    """Build an explainable channel baseline from recent public uploads.

    Prefer recent uploads with the same coarse format as the candidate
    (Short vs Long-form). If there are not enough same-format uploads,
    fall back to all recent public uploads. The candidate itself is always
    excluded from its own baseline.
    """
    usable = [
        sample
        for sample in samples
        if sample.get("id") != candidate_id and int(sample.get("views") or 0) > 0
    ]
    same_format = [
        sample for sample in usable if sample.get("type") == candidate_type
    ]

    if len(same_format) >= min_samples:
        pool = same_format
        scope = "same-format"
    elif len(usable) >= min_samples:
        pool = usable
        scope = "all-formats"
    else:
        return {
            "baseline": None,
            "outlier": None,
            "baselineSampleSize": len(usable),
            "baselineScope": "insufficient-sample",
            "baselineMethod": "median-views",
        }

    baseline = float(median(int(sample["views"]) for sample in pool))
    if baseline <= 0:
        return {
            "baseline": None,
            "outlier": None,
            "baselineSampleSize": len(pool),
            "baselineScope": scope,
            "baselineMethod": "median-views",
        }

    return {
        "baseline": int(round(baseline)),
        "outlier": round(max(candidate_views, 0) / baseline, 2),
        "baselineSampleSize": len(pool),
        "baselineScope": scope,
        "baselineMethod": "median-views",
    }

from __future__ import annotations

import re
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

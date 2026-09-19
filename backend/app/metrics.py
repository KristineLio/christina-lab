from __future__ import annotations

import re
from datetime import datetime, timezone
from statistics import median


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


def age_hours(published_at: datetime, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    return max((now - published_at).total_seconds() / 3600, 1.0)


def human_age(published_at: datetime, now: datetime | None = None) -> str:
    hours = age_hours(published_at, now=now)
    if hours < 1:
        return "<1h"
    if hours < 24:
        return f"{int(hours)}h"
    days = hours / 24
    if days < 30:
        return f"{int(days)}d"
    return f"{int(days / 30)}mo"


def calculate_video_metrics(
    *,
    views: int,
    likes: int,
    comments: int,
    subscribers: int | None,
    published_at: datetime,
    now: datetime | None = None,
) -> dict[str, float | None]:
    current_age_hours = age_hours(published_at, now=now)
    views_hour = views / current_age_hours
    views_day = views / max(current_age_hours / 24, 1 / 24)
    engagement = ((likes + comments) / views * 100) if views > 0 else 0.0
    views_sub = (views / subscribers) if subscribers and subscribers > 0 else None

    return {
        "ageHours": round(current_age_hours, 2),
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
    candidate_published_at: datetime,
    samples: list[dict],
    min_samples: int = 3,
    now: datetime | None = None,
) -> dict[str, int | float | str | None]:
    """Build an age-adjusted baseline from recent public channel uploads.

    YouTube's public Data API exposes each video's current cumulative views,
    but not a historical "views at exactly 6 hours" series for old videos.
    To avoid unfairly comparing a six-hour-old video with older videos'
    lifetime totals, Christina Lab compares average view velocity instead:

        candidate views / candidate age
        --------------------------------
        median(recent video views / recent video age)

    The median channel velocity is then projected to the candidate's current
    age to produce an explainable "expected views by this age" baseline.

    This is an age-adjusted public-data approximation. Once Christina Lab
    stores its own snapshots over time, it can graduate to true same-age
    historical baselines.
    """
    now = now or datetime.now(timezone.utc)
    candidate_age = age_hours(candidate_published_at, now=now)

    usable = []
    for sample in samples:
        if sample.get("id") == candidate_id:
            continue
        views = int(sample.get("views") or 0)
        published_at = sample.get("publishedAt")
        if views <= 0 or not isinstance(published_at, datetime):
            continue

        sample_age = age_hours(published_at, now=now)
        usable.append(
            {
                **sample,
                "views": views,
                "ageHours": sample_age,
                "viewsHour": views / sample_age,
            }
        )

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
            "baselineVelocity": None,
            "candidateAgeHours": round(candidate_age, 2),
            "baselineSampleSize": len(usable),
            "baselineScope": "insufficient-sample",
            "baselineMethod": "median-age-adjusted-velocity",
        }

    baseline_velocity = float(median(sample["viewsHour"] for sample in pool))
    if baseline_velocity <= 0:
        return {
            "baseline": None,
            "outlier": None,
            "baselineVelocity": None,
            "candidateAgeHours": round(candidate_age, 2),
            "baselineSampleSize": len(pool),
            "baselineScope": scope,
            "baselineMethod": "median-age-adjusted-velocity",
        }

    expected_views_at_age = baseline_velocity * candidate_age
    candidate_velocity = max(candidate_views, 0) / candidate_age

    return {
        # "baseline" now means expected views by the candidate's current age,
        # not median lifetime views.
        "baseline": int(round(expected_views_at_age)),
        "outlier": round(candidate_velocity / baseline_velocity, 2),
        "baselineVelocity": round(baseline_velocity, 2),
        "candidateAgeHours": round(candidate_age, 2),
        "baselineSampleSize": len(pool),
        "baselineScope": scope,
        "baselineMethod": "median-age-adjusted-velocity",
    }

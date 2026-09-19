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
        "viewsSub": round(views_sub, 6) if views_sub is not None else None,
    }


def calculate_channel_baseline(
    *,
    candidate_id: str,
    candidate_views: int,
    candidate_type: str,
    candidate_published_at: datetime,
    samples: list[dict],
    min_samples: int = 3,
    max_samples: int = 12,
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

    Live and upcoming videos are excluded from the comparison pool because
    their current totals are not stable baseline samples. The comparison pool
    is capped at the most recent usable samples so older channel history does
    not dominate the baseline.

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
        live_state = sample.get("liveBroadcastContent", "none")
        if live_state in {"live", "upcoming"}:
            continue
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
        pool = same_format[:max_samples]
        scope = "same-format"
    elif len(usable) >= min_samples:
        pool = usable[:max_samples]
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



def _piecewise_score(value: float, points: list[tuple[float, float]]) -> float:
    """Linearly interpolate a bounded score across transparent breakpoints."""
    if value <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if value <= x1:
            if x1 == x0:
                return y1
            ratio = (value - x0) / (x1 - x0)
            return y0 + ratio * (y1 - y0)
    return points[-1][1]



def _format_views_subscriber_ratio(value: float) -> str:
    """Format tiny audience ratios without rounding them to a misleading 0.00×."""
    ratio = max(float(value), 0.0)
    percent = ratio * 100

    if ratio >= 0.1:
        ratio_text = f"{ratio:.2f}×"
    elif ratio >= 0.001:
        ratio_text = f"{ratio:.3f}×"
    else:
        ratio_text = f"{ratio:.4f}×"

    if percent >= 1:
        percent_text = f"{percent:.1f}%"
    elif percent >= 0.1:
        percent_text = f"{percent:.2f}%"
    else:
        percent_text = f"{percent:.3f}%"

    return f"Views/subscriber: {ratio_text} ({percent_text} of subscribers)"

def calculate_opportunity_score(
    *,
    views: int,
    subscribers: int | None,
    views_day: float,
    engagement: float,
    views_sub: float | None,
    age_hours_value: float,
    outlier: float | None,
    baseline_sample_size: int,
    baseline_scope: str,
    baseline_method: str = "historical-snapshot-median",
    live_broadcast_content: str = "none",
) -> dict:
    """Calculate Christina Lab's explainable 0-100 Opportunity Score.

    Components intentionally sum to 100 before guardrails:
      - age-adjusted outlier: 40
      - 24h run rate: 20
      - engagement: 15
      - views/subscriber: 10
      - freshness: 10
      - baseline confidence: 5

    Guardrails keep tiny-channel ratios, weak traction, missing baselines, and
    live/upcoming content from dominating the ranking. Low traction is handled
    with a continuous confidence multiplier rather than hard view-count cliffs.
    """
    components: list[dict] = []
    guardrails: list[dict] = []

    historical_baseline = baseline_method == "historical-snapshot-median"
    outlier_points = 0
    if outlier is not None:
        outlier_points = round(
            _piecewise_score(
                max(outlier, 0),
                [(0, 0), (0.5, 0), (1, 8), (2, 20), (4, 32), (8, 40)],
            )
        )

        # Until real same-age history exists, do not let the lifetime-velocity
        # approximation contribute the full 40 outlier points.
        if not historical_baseline and outlier_points > 24:
            outlier_points = 24
            guardrails.append(
                {
                    "type": "component-cap",
                    "key": "provisional-baseline",
                    "label": (
                        "Outlier contribution limited to 24/40 while Christina Lab "
                        "collects true same-age historical snapshots."
                    ),
                }
            )

    components.append(
        {
            "key": "outlier",
            "score": outlier_points,
            "max": 40,
            "label": (
                (
                    f"Historical same-age outlier: {outlier:.1f}×"
                    if historical_baseline
                    else f"Estimated age-adjusted outlier: {outlier:.1f}×"
                )
                if outlier is not None
                else "Outlier unavailable"
            ),
        }
    )

    velocity_points = round(
        _piecewise_score(
            max(float(views_day or 0), 0),
            [(0, 0), (500, 1), (1000, 3), (5000, 8), (20_000, 13), (100_000, 18), (250_000, 20)],
        )
    )
    components.append(
        {
            "key": "velocity",
            "score": velocity_points,
            "max": 20,
            "label": f"24h run rate: {int(round(views_day or 0)):,}",
        }
    )

    engagement_points = round(
        _piecewise_score(
            max(float(engagement or 0), 0),
            [(0, 0), (0.5, 1), (1, 3), (2, 6), (4, 10), (8, 15)],
        )
    )
    components.append(
        {
            "key": "engagement",
            "score": engagement_points,
            "max": 15,
            "label": f"Engagement: {float(engagement or 0):.2f}%",
        }
    )

    audience_points = 0
    if views_sub is not None:
        audience_points = round(
            _piecewise_score(
                max(float(views_sub), 0),
                [(0, 0), (0.05, 1), (0.1, 2), (0.25, 4), (0.5, 6), (1, 8), (2, 10)],
            )
        )

    if subscribers is not None and subscribers < 100:
        original = audience_points
        audience_points = min(audience_points, 4)
        if original > audience_points:
            guardrails.append(
                {
                    "type": "component-cap",
                    "key": "tiny-channel-ratio",
                    "label": "Views/subscriber contribution capped because the channel has fewer than 100 subscribers.",
                }
            )
    elif subscribers is not None and subscribers < 1000:
        original = audience_points
        audience_points = min(audience_points, 7)
        if original > audience_points:
            guardrails.append(
                {
                    "type": "component-cap",
                    "key": "small-channel-ratio",
                    "label": "Views/subscriber contribution capped because the channel has fewer than 1,000 subscribers.",
                }
            )

    components.append(
        {
            "key": "audience",
            "score": audience_points,
            "max": 10,
            "label": (
                _format_views_subscriber_ratio(views_sub)
                if views_sub is not None
                else "Views/subscriber unavailable"
            ),
        }
    )

    age = max(float(age_hours_value or 0), 0)
    if age <= 6:
        freshness_points = 10
    elif age <= 24:
        freshness_points = 9
    elif age <= 72:
        freshness_points = 7
    elif age <= 168:
        freshness_points = 4
    elif age <= 720:
        freshness_points = 1
    else:
        freshness_points = 0
    components.append(
        {
            "key": "freshness",
            "score": freshness_points,
            "max": 10,
            "label": f"Fresh signal: {age:.1f}h old",
        }
    )

    confidence_points = 0
    if outlier is not None:
        if baseline_sample_size >= 9:
            confidence_points = 5
        elif baseline_sample_size >= 6:
            confidence_points = 4
        elif baseline_sample_size >= 4:
            confidence_points = 3
        elif baseline_sample_size >= 3:
            confidence_points = 2

        if baseline_scope == "all-formats" and confidence_points > 0:
            confidence_points = max(confidence_points - 1, 1)

        if not historical_baseline:
            confidence_points = min(confidence_points, 2)

    components.append(
        {
            "key": "confidence",
            "score": confidence_points,
            "max": 5,
            "label": (
                f"Baseline confidence: {baseline_sample_size} comparison videos"
                if outlier is not None
                else "Baseline confidence unavailable"
            ),
        }
    )

    raw_score = sum(component["score"] for component in components)
    score = raw_score

    live_state = live_broadcast_content or "none"
    if live_state == "live":
        score = max(score - 5, 0)
        guardrails.append(
            {
                "type": "penalty",
                "key": "live-content",
                "value": -5,
                "label": "Live content penalty: current run rate can be unusually inflated during a stream.",
            }
        )
    elif live_state == "upcoming":
        score = min(score, 20)
        guardrails.append(
            {
                "type": "cap",
                "key": "upcoming-content",
                "value": 20,
                "label": "Upcoming content is capped at 20 until it has real post-publish performance.",
            }
        )

    if outlier is None:
        score = min(score, 55)
        guardrails.append(
            {
                "type": "cap",
                "key": "missing-baseline",
                "value": 55,
                "label": "Opportunity capped at 55 because there is no stable channel baseline yet.",
            }
        )

    # Traction confidence is continuous rather than a hard view-count cliff.
    # At very low view counts, engagement/outlier ratios are noisy, so the
    # score is discounted. Confidence rises smoothly to 100% by 1,000 views.
    traction_factor = _piecewise_score(
        max(float(views or 0), 0),
        [
            (0, 0.50),
            (100, 0.60),
            (300, 0.75),
            (600, 0.90),
            (1000, 1.00),
        ],
    )
    if traction_factor < 1:
        score_before_traction = score
        score = score * traction_factor
        guardrails.append(
            {
                "type": "multiplier",
                "key": "traction-confidence",
                "value": round(traction_factor, 3),
                "label": (
                    f"Traction confidence {traction_factor * 100:.0f}% at {views:,} views: "
                    f"score adjusted gradually from {round(score_before_traction)} "
                    f"to {round(score)}."
                ),
            }
        )

    score = int(max(0, min(round(score), 100)))

    return {
        "opportunity": score,
        "opportunityRaw": int(round(raw_score)),
        "opportunityComponents": components,
        "opportunityGuardrails": guardrails,
        "opportunityScoreVersion": "v1.2",
        "opportunityBaselineMethod": baseline_method,
    }

from datetime import datetime, timedelta, timezone

from backend.app.metrics import (
    calculate_channel_baseline,
    calculate_opportunity_score,
    calculate_video_metrics,
    format_duration,
    parse_youtube_duration,
)


def test_parse_youtube_duration():
    assert parse_youtube_duration("PT12M18S") == 738
    assert parse_youtube_duration("PT1H2M3S") == 3723
    assert parse_youtube_duration("PT48S") == 48


def test_format_duration():
    assert format_duration(48) == "0:48"
    assert format_duration(738) == "12:18"
    assert format_duration(3723) == "1:02:03"


def test_calculate_video_metrics():
    now = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)
    published = now - timedelta(hours=24)

    result = calculate_video_metrics(
        views=24_000,
        likes=1_000,
        comments=200,
        subscribers=12_000,
        published_at=published,
        now=now,
    )

    assert result["ageHours"] == 24
    assert result["viewsHour"] == 1000
    assert result["viewsDay"] == 24000
    assert result["engagement"] == 5.0
    assert result["viewsSub"] == 2.0


def test_age_adjusted_baseline_prefers_same_format():
    now = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)
    candidate_published = now - timedelta(hours=6)

    # Same-format uploads average 100 views/hour despite very different ages.
    samples = [
        {
            "id": "a",
            "views": 1200,
            "type": "Short",
            "publishedAt": now - timedelta(hours=12),
        },
        {
            "id": "b",
            "views": 2400,
            "type": "Short",
            "publishedAt": now - timedelta(hours=24),
        },
        {
            "id": "c",
            "views": 4800,
            "type": "Short",
            "publishedAt": now - timedelta(hours=48),
        },
        {
            "id": "d",
            "views": 100_000,
            "type": "Long-form",
            "publishedAt": now - timedelta(hours=10),
        },
    ]

    result = calculate_channel_baseline(
        candidate_id="candidate",
        candidate_views=1200,
        candidate_type="Short",
        candidate_published_at=candidate_published,
        samples=samples,
        now=now,
    )

    # Typical channel velocity is 100 views/hour, so at 6h the expected
    # baseline is 600 views. 1,200 views is therefore a 2.0x outlier.
    assert result["baselineVelocity"] == 100
    assert result["baseline"] == 600
    assert result["outlier"] == 2.0
    assert result["candidateAgeHours"] == 6
    assert result["baselineSampleSize"] == 3
    assert result["baselineScope"] == "same-format"
    assert result["baselineMethod"] == "median-age-adjusted-velocity"


def test_age_adjusted_baseline_excludes_candidate_and_falls_back_to_all_formats():
    now = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)
    candidate_published = now - timedelta(hours=10)

    samples = [
        {
            "id": "candidate",
            "views": 999_999,
            "type": "Long-form",
            "publishedAt": candidate_published,
        },
        {
            "id": "a",
            "views": 1000,
            "type": "Short",
            "publishedAt": now - timedelta(hours=10),
        },
        {
            "id": "b",
            "views": 2000,
            "type": "Short",
            "publishedAt": now - timedelta(hours=20),
        },
        {
            "id": "c",
            "views": 4000,
            "type": "Short",
            "publishedAt": now - timedelta(hours=40),
        },
    ]

    result = calculate_channel_baseline(
        candidate_id="candidate",
        candidate_views=1500,
        candidate_type="Long-form",
        candidate_published_at=candidate_published,
        samples=samples,
        now=now,
    )

    # All three usable uploads have 100 views/hour, so expected views at 10h
    # are 1,000 and the candidate is performing at 1.5x.
    assert result["baseline"] == 1000
    assert result["outlier"] == 1.5
    assert result["baselineScope"] == "all-formats"


def test_age_adjusted_baseline_requires_minimum_sample():
    now = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)

    result = calculate_channel_baseline(
        candidate_id="candidate",
        candidate_views=10_000,
        candidate_type="Short",
        candidate_published_at=now - timedelta(hours=6),
        samples=[
            {
                "id": "a",
                "views": 1000,
                "type": "Short",
                "publishedAt": now - timedelta(hours=12),
            },
            {
                "id": "b",
                "views": 2000,
                "type": "Short",
                "publishedAt": now - timedelta(hours=24),
            },
        ],
        now=now,
    )

    assert result["baseline"] is None
    assert result["outlier"] is None
    assert result["baselineScope"] == "insufficient-sample"


def test_new_video_is_not_penalized_against_older_lifetime_totals():
    now = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)

    # Candidate: 500 views after 5h = 100 views/hour.
    # Older videos: much larger lifetime totals, but the same average velocity.
    samples = [
        {
            "id": "a",
            "views": 2400,
            "type": "Short",
            "publishedAt": now - timedelta(hours=24),
        },
        {
            "id": "b",
            "views": 4800,
            "type": "Short",
            "publishedAt": now - timedelta(hours=48),
        },
        {
            "id": "c",
            "views": 7200,
            "type": "Short",
            "publishedAt": now - timedelta(hours=72),
        },
    ]

    result = calculate_channel_baseline(
        candidate_id="candidate",
        candidate_views=500,
        candidate_type="Short",
        candidate_published_at=now - timedelta(hours=5),
        samples=samples,
        now=now,
    )

    assert result["baseline"] == 500
    assert result["outlier"] == 1.0



def test_baseline_ignores_live_and_upcoming_samples():
    now = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)
    samples = [
        {
            "id": "live",
            "views": 100_000,
            "type": "Long-form",
            "publishedAt": now - timedelta(hours=2),
            "liveBroadcastContent": "live",
        },
        {
            "id": "upcoming",
            "views": 500,
            "type": "Long-form",
            "publishedAt": now - timedelta(hours=1),
            "liveBroadcastContent": "upcoming",
        },
        {
            "id": "a",
            "views": 2400,
            "type": "Long-form",
            "publishedAt": now - timedelta(hours=24),
            "liveBroadcastContent": "none",
        },
        {
            "id": "b",
            "views": 4800,
            "type": "Long-form",
            "publishedAt": now - timedelta(hours=48),
            "liveBroadcastContent": "none",
        },
        {
            "id": "c",
            "views": 7200,
            "type": "Long-form",
            "publishedAt": now - timedelta(hours=72),
            "liveBroadcastContent": "none",
        },
    ]

    result = calculate_channel_baseline(
        candidate_id="candidate",
        candidate_views=500,
        candidate_type="Long-form",
        candidate_published_at=now - timedelta(hours=5),
        samples=samples,
        now=now,
    )

    assert result["baselineSampleSize"] == 3
    assert result["baselineVelocity"] == 100
    assert result["baseline"] == 500
    assert result["outlier"] == 1.0


def test_baseline_caps_comparison_pool_to_most_recent_usable_samples():
    now = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)
    samples = []
    for index in range(20):
        hours = 24 + index
        samples.append(
            {
                "id": f"v{index}",
                "views": hours * 100,
                "type": "Short",
                "publishedAt": now - timedelta(hours=hours),
                "liveBroadcastContent": "none",
            }
        )

    result = calculate_channel_baseline(
        candidate_id="candidate",
        candidate_views=500,
        candidate_type="Short",
        candidate_published_at=now - timedelta(hours=5),
        samples=samples,
        max_samples=12,
        now=now,
    )

    assert result["baselineSampleSize"] == 12
    assert result["baselineVelocity"] == 100
    assert result["outlier"] == 1.0



def test_opportunity_score_is_explainable_and_bounded():
    result = calculate_opportunity_score(
        views=50_000,
        subscribers=25_000,
        views_day=42_000,
        engagement=7.2,
        views_sub=2.0,
        age_hours_value=12,
        outlier=5.8,
        baseline_sample_size=10,
        baseline_scope="same-format",
        live_broadcast_content="none",
    )

    assert 0 <= result["opportunity"] <= 100
    assert result["opportunity"] >= 80
    assert result["opportunityRaw"] == sum(
        component["score"] for component in result["opportunityComponents"]
    )
    assert [component["max"] for component in result["opportunityComponents"]] == [
        40,
        20,
        15,
        10,
        10,
        5,
    ]
    assert result["opportunityScoreVersion"] == "v1.1"


def test_tiny_channel_breakout_cannot_dominate_on_ratio_alone():
    result = calculate_opportunity_score(
        views=255,
        subscribers=4,
        views_day=800,
        engagement=2.0,
        views_sub=63.75,
        age_hours_value=8,
        outlier=8.0,
        baseline_sample_size=5,
        baseline_scope="same-format",
        live_broadcast_content="none",
    )

    audience = next(
        component
        for component in result["opportunityComponents"]
        if component["key"] == "audience"
    )
    assert audience["score"] <= 4
    assert result["opportunity"] < result["opportunityRaw"]
    assert any(
        guardrail["key"] == "tiny-channel-ratio"
        for guardrail in result["opportunityGuardrails"]
    )
    traction = next(
        guardrail
        for guardrail in result["opportunityGuardrails"]
        if guardrail["key"] == "traction-confidence"
    )
    assert 0.70 < traction["value"] < 0.75


def test_missing_baseline_caps_opportunity():
    result = calculate_opportunity_score(
        views=20_000,
        subscribers=10_000,
        views_day=100_000,
        engagement=8.0,
        views_sub=2.0,
        age_hours_value=4,
        outlier=None,
        baseline_sample_size=1,
        baseline_scope="insufficient-sample",
        live_broadcast_content="none",
    )

    assert result["opportunity"] <= 55
    assert any(
        guardrail["key"] == "missing-baseline"
        for guardrail in result["opportunityGuardrails"]
    )


def test_live_content_gets_velocity_guardrail_penalty():
    normal = calculate_opportunity_score(
        views=20_000,
        subscribers=100_000,
        views_day=250_000,
        engagement=1.0,
        views_sub=0.2,
        age_hours_value=2,
        outlier=1.1,
        baseline_sample_size=9,
        baseline_scope="same-format",
        live_broadcast_content="none",
    )
    live = calculate_opportunity_score(
        views=20_000,
        subscribers=100_000,
        views_day=250_000,
        engagement=1.0,
        views_sub=0.2,
        age_hours_value=2,
        outlier=1.1,
        baseline_sample_size=9,
        baseline_scope="same-format",
        live_broadcast_content="live",
    )

    assert live["opportunity"] == normal["opportunity"] - 5
    assert any(
        guardrail["key"] == "live-content"
        for guardrail in live["opportunityGuardrails"]
    )



def test_views_subscriber_keeps_precision_for_large_channels():
    now = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)
    result = calculate_video_metrics(
        views=578,
        likes=50,
        comments=8,
        subscribers=222_000,
        published_at=now - timedelta(hours=7),
        now=now,
    )

    assert result["viewsSub"] == 0.002604

    opportunity = calculate_opportunity_score(
        views=578,
        subscribers=222_000,
        views_day=result["viewsDay"],
        engagement=result["engagement"],
        views_sub=result["viewsSub"],
        age_hours_value=result["ageHours"],
        outlier=3.4,
        baseline_sample_size=12,
        baseline_scope="same-format",
        live_broadcast_content="none",
    )
    audience = next(
        component
        for component in opportunity["opportunityComponents"]
        if component["key"] == "audience"
    )
    assert "0.003×" in audience["label"]
    assert "0.26%" in audience["label"]


def test_traction_confidence_has_no_999_to_1000_view_cliff():
    common = dict(
        subscribers=20_000,
        views_day=30_000,
        engagement=6.0,
        views_sub=0.05,
        age_hours_value=8,
        outlier=4.0,
        baseline_sample_size=9,
        baseline_scope="same-format",
        live_broadcast_content="none",
    )
    just_below = calculate_opportunity_score(views=999, **common)
    at_threshold = calculate_opportunity_score(views=1000, **common)

    assert abs(at_threshold["opportunity"] - just_below["opportunity"]) <= 1
    traction = next(
        guardrail
        for guardrail in just_below["opportunityGuardrails"]
        if guardrail["key"] == "traction-confidence"
    )
    assert traction["value"] > 0.99
    assert not any(
        guardrail["key"] == "traction-confidence"
        for guardrail in at_threshold["opportunityGuardrails"]
    )

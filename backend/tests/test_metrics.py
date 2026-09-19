from datetime import datetime, timedelta, timezone

from backend.app.metrics import (
    calculate_channel_baseline,
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

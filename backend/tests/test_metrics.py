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

    assert result["viewsHour"] == 1000
    assert result["viewsDay"] == 24000
    assert result["engagement"] == 5.0
    assert result["viewsSub"] == 2.0



def test_channel_baseline_prefers_same_format():
    samples = [
        {"id": "a", "views": 1000, "type": "Short"},
        {"id": "b", "views": 2000, "type": "Short"},
        {"id": "c", "views": 3000, "type": "Short"},
        {"id": "d", "views": 50_000, "type": "Long-form"},
    ]

    result = calculate_channel_baseline(
        candidate_id="candidate",
        candidate_views=10_000,
        candidate_type="Short",
        samples=samples,
    )

    assert result["baseline"] == 2000
    assert result["outlier"] == 5.0
    assert result["baselineSampleSize"] == 3
    assert result["baselineScope"] == "same-format"


def test_channel_baseline_excludes_candidate_and_falls_back_to_all_formats():
    samples = [
        {"id": "candidate", "views": 99_999, "type": "Long-form"},
        {"id": "a", "views": 1000, "type": "Short"},
        {"id": "b", "views": 2000, "type": "Short"},
        {"id": "c", "views": 3000, "type": "Short"},
    ]

    result = calculate_channel_baseline(
        candidate_id="candidate",
        candidate_views=6000,
        candidate_type="Long-form",
        samples=samples,
    )

    assert result["baseline"] == 2000
    assert result["outlier"] == 3.0
    assert result["baselineSampleSize"] == 3
    assert result["baselineScope"] == "all-formats"


def test_channel_baseline_requires_minimum_sample():
    result = calculate_channel_baseline(
        candidate_id="candidate",
        candidate_views=10_000,
        candidate_type="Short",
        samples=[
            {"id": "a", "views": 1000, "type": "Short"},
            {"id": "b", "views": 2000, "type": "Short"},
        ],
    )

    assert result["baseline"] is None
    assert result["outlier"] is None
    assert result["baselineScope"] == "insufficient-sample"

from datetime import datetime, timedelta, timezone

from app.metrics import (
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

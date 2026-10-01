from backend.app.clip_lab import (
    _fallback_moments,
    _segment_window,
    _srt_time,
)


def _segments():
    return [
        {"start": 0.0, "end": 6.0, "text": "Most people think a working app is enough."},
        {"start": 6.0, "end": 13.0, "text": "But the biggest problem is that it does not show how you think."},
        {"start": 13.0, "end": 21.0, "text": "So I rebuilt the project around structure reliability and proof."},
        {"start": 21.0, "end": 29.0, "text": "The result was still a weather app, but the engineering changed."},
        {"start": 29.0, "end": 37.0, "text": "That is why I added caching tests and separate layers."},
        {"start": 37.0, "end": 45.0, "text": "Now the project shows what happens when things fail."},
        {"start": 45.0, "end": 53.0, "text": "Here is the part I would have skipped when I started."},
        {"start": 53.0, "end": 61.0, "text": "I wrote integration tests for storage and refresh behavior."},
        {"start": 61.0, "end": 69.0, "text": "That proof matters more than another flashy feature."},
    ]


def test_fallback_moments_returns_non_overlapping_clip_candidates():
    moments = _fallback_moments(_segments(), count=2, min_seconds=20, max_seconds=35)

    assert len(moments) == 2
    assert all(moment["endSeconds"] > moment["startSeconds"] for moment in moments)
    first, second = moments
    overlap = max(
        0,
        min(first["endSeconds"], second["endSeconds"])
        - max(first["startSeconds"], second["startSeconds"]),
    )
    shorter = min(
        first["endSeconds"] - first["startSeconds"],
        second["endSeconds"] - second["startSeconds"],
    )
    assert overlap / shorter <= 0.45


def test_segment_window_respects_duration_bounds_and_boundaries():
    start, end = _segment_window(
        _segments(),
        requested_start=7,
        requested_end=11,
        min_seconds=20,
        max_seconds=30,
        total_duration=69,
    )

    assert 0 <= start < end <= 69
    assert 20 <= end - start <= 30


def test_srt_time_formats_milliseconds():
    assert _srt_time(0) == "00:00:00,000"
    assert _srt_time(65.432) == "00:01:05,432"

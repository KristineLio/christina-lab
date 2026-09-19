from datetime import datetime, timedelta, timezone

from backend.app.storage import SnapshotStore
from backend.app.youtube import _video_classification


def _video(
    *,
    video_id: str,
    channel_id: str = "channel-1",
    title: str = "Video",
    published_at: datetime,
    content_type: str = "Short",
    live_status: str = "none",
    views: int = 100,
    likes: int = 10,
    comments: int = 1,
    subscribers: int = 1000,
) -> dict:
    return {
        "id": video_id,
        "channelId": channel_id,
        "title": title,
        "publishedAt": published_at,
        "type": content_type,
        "liveStatus": live_status,
        "durationSeconds": 30 if content_type == "Short" else 600,
        "views": views,
        "likes": likes,
        "comments": comments,
        "subscribers": subscribers,
    }


def test_snapshot_store_records_growth_over_time(tmp_path):
    db = tmp_path / "christina_lab.sqlite3"
    store = SnapshotStore(f"sqlite:///{db}")
    published = datetime(2026, 9, 19, 10, 0, tzinfo=timezone.utc)

    first_seen = datetime(2026, 9, 19, 11, 0, tzinfo=timezone.utc)
    later = datetime(2026, 9, 19, 16, 0, tzinfo=timezone.utc)

    inserted = store.record_snapshots(
        [_video(video_id="v1", published_at=published, views=100)],
        observed_at=first_seen,
        min_interval_minutes=0,
    )
    inserted += store.record_snapshots(
        [_video(video_id="v1", published_at=published, views=800)],
        observed_at=later,
        min_interval_minutes=0,
    )

    snapshots = store.video_snapshots("v1")
    assert inserted == 2
    assert [row["ageHours"] for row in snapshots] == [1.0, 6.0]
    assert [row["views"] for row in snapshots] == [100, 800]


def test_snapshot_store_deduplicates_rapid_rechecks(tmp_path):
    db = tmp_path / "christina_lab.sqlite3"
    store = SnapshotStore(f"sqlite:///{db}")
    published = datetime(2026, 9, 19, 10, 0, tzinfo=timezone.utc)
    observed = datetime(2026, 9, 19, 11, 0, tzinfo=timezone.utc)

    assert store.record_snapshots(
        [_video(video_id="v1", published_at=published, views=100)],
        observed_at=observed,
    ) == 1
    assert store.record_snapshots(
        [_video(video_id="v1", published_at=published, views=120)],
        observed_at=observed + timedelta(minutes=5),
    ) == 0
    assert len(store.video_snapshots("v1")) == 1


def test_same_age_baseline_uses_historical_snapshots(tmp_path):
    db = tmp_path / "christina_lab.sqlite3"
    store = SnapshotStore(f"sqlite:///{db}")
    observed = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)

    # Three prior Shorts were actually observed around age six hours.
    for index, views in enumerate([500, 600, 700], start=1):
        published = observed - timedelta(hours=6)
        store.record_snapshots(
            [
                _video(
                    video_id=f"old-{index}",
                    published_at=published,
                    views=views,
                    content_type="Short",
                )
            ],
            observed_at=observed,
            min_interval_minutes=0,
        )

    result = store.same_age_baseline(
        channel_id="channel-1",
        content_type="Short",
        candidate_id="candidate",
        target_age_hours=6,
    )

    assert result["ready"] is True
    assert result["baseline"] == 600
    assert result["sampleSize"] == 3
    assert result["method"] == "historical-snapshot-median"


def test_same_age_baseline_does_not_mix_content_types(tmp_path):
    db = tmp_path / "christina_lab.sqlite3"
    store = SnapshotStore(f"sqlite:///{db}")
    observed = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)

    for index in range(3):
        store.record_snapshots(
            [
                _video(
                    video_id=f"live-{index}",
                    published_at=observed - timedelta(hours=6),
                    views=5000,
                    content_type="Livestream",
                    live_status="replay",
                )
            ],
            observed_at=observed,
            min_interval_minutes=0,
        )

    result = store.same_age_baseline(
        channel_id="channel-1",
        content_type="Short",
        candidate_id="candidate",
        target_age_hours=6,
    )

    assert result["ready"] is False
    assert result["sampleSize"] == 0


def test_video_classification_separates_short_long_and_livestream():
    short = {"snippet": {"liveBroadcastContent": "none"}}
    long_form = {"snippet": {"liveBroadcastContent": "none"}}
    live = {"snippet": {"liveBroadcastContent": "live"}}
    replay = {
        "snippet": {"liveBroadcastContent": "none"},
        "liveStreamingDetails": {"actualStartTime": "2026-09-19T10:00:00Z"},
    }

    assert _video_classification(short, 45) == ("Short", "none")
    assert _video_classification(long_form, 600) == ("Long-form", "none")
    assert _video_classification(live, 600) == ("Livestream", "live")
    assert _video_classification(replay, 600) == ("Livestream", "replay")

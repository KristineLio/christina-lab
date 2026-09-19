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


def _record_candidate_analyses(
    store: SnapshotStore,
    video_ids: list[str],
    observed: datetime,
    *,
    topic: str = "test topic",
) -> None:
    store.record_analyses(
        [
            {
                "id": video_id,
                "opportunity": 50 + index,
                "outlier": 2.0 + index / 10,
                "baseline": 500,
                "baselineMethod": "median-age-adjusted-velocity",
                "baselineSampleSize": 6,
                "viewsDay": 10_000 + index * 100,
                "engagement": 5.0,
                "viewsSub": 0.5,
            }
            for index, video_id in enumerate(video_ids, start=1)
        ],
        topic=topic,
        observed_at=observed,
    )


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



def test_dashboard_summary_uses_real_persisted_analysis(tmp_path):
    db = tmp_path / "christina_lab.sqlite3"
    store = SnapshotStore(f"sqlite:///{db}")
    published = datetime(2026, 9, 19, 10, 0, tzinfo=timezone.utc)
    observed = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)

    video = _video(
        video_id="candidate-1",
        channel_id="channel-a",
        title="Why AI Tools Fail Beginners",
        published_at=published,
        content_type="Long-form",
        views=5000,
        likes=400,
        comments=50,
        subscribers=20_000,
    )
    video["channel"] = "Creator A"
    video["thumbnail"] = "https://example.com/thumb.jpg"
    video["youtubeUrl"] = "https://www.youtube.com/watch?v=candidate-1"

    store.record_snapshots([video], observed_at=observed, min_interval_minutes=0)
    store.record_analyses(
        [
            {
                "id": "candidate-1",
                "opportunity": 82,
                "outlier": 4.2,
                "baseline": 1200,
                "baselineMethod": "historical-snapshot-median",
                "baselineSampleSize": 6,
                "viewsDay": 60_000,
                "engagement": 9.0,
                "viewsSub": 0.25,
            }
        ],
        topic="AI tools",
        observed_at=observed,
    )

    dashboard = store.dashboard_summary()

    assert dashboard["metrics"]["videosTracked"] == 1
    assert dashboard["metrics"]["analyzedCandidates"] == 1
    assert dashboard["metrics"]["topicsTracked"] == 1
    assert dashboard["topOpportunities"][0]["title"] == "Why AI Tools Fail Beginners"
    assert dashboard["topOpportunities"][0]["channel"] == "Creator A"
    assert dashboard["topOpportunities"][0]["opportunity"] == 82
    assert dashboard["topOpportunities"][0]["topic"] == "AI tools"


def test_dashboard_actual_growth_requires_two_snapshots(tmp_path):
    db = tmp_path / "christina_lab.sqlite3"
    store = SnapshotStore(f"sqlite:///{db}")
    published = datetime(2026, 9, 19, 10, 0, tzinfo=timezone.utc)

    video = _video(
        video_id="growth-1",
        channel_id="channel-a",
        title="Growth Test",
        published_at=published,
        content_type="Short",
        views=100,
    )
    store.record_snapshots(
        [video],
        observed_at=datetime(2026, 9, 19, 11, 0, tzinfo=timezone.utc),
        min_interval_minutes=0,
    )
    video["views"] = 700
    store.record_snapshots(
        [video],
        observed_at=datetime(2026, 9, 19, 14, 0, tzinfo=timezone.utc),
        min_interval_minutes=0,
    )

    dashboard = store.dashboard_summary()

    assert dashboard["metrics"]["videosWithMultipleSnapshots"] == 1
    assert dashboard["fastestActualGrowth"][0]["deltaViews"] == 600
    assert dashboard["fastestActualGrowth"][0]["actualViewsHour"] == 200.0


def test_patterns_summary_comes_from_persisted_topics_titles_and_types(tmp_path):
    db = tmp_path / "christina_lab.sqlite3"
    store = SnapshotStore(f"sqlite:///{db}")
    observed = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)

    titles = [
        "AI Tools Beginners Should Avoid",
        "AI Tools Beginners Actually Need",
        "AI Tools Workflow for Beginners",
    ]
    analysis_rows = []
    for index, title in enumerate(titles, start=1):
        video_id = f"ai-{index}"
        video = _video(
            video_id=video_id,
            channel_id=f"channel-{index}",
            title=title,
            published_at=observed - timedelta(hours=6),
            content_type="Short",
            views=1000 * index,
            likes=100 * index,
            comments=10 * index,
        )
        store.record_snapshots([video], observed_at=observed, min_interval_minutes=0)
        analysis_rows.append(
            {
                "id": video_id,
                "opportunity": 60 + index * 5,
                "outlier": 2.0 + index,
                "baseline": 500,
                "baselineMethod": "median-age-adjusted-velocity",
                "baselineSampleSize": 6,
                "viewsDay": 10_000 * index,
                "engagement": 5.0,
                "viewsSub": 0.5,
            }
        )

    store.record_analyses(analysis_rows, topic="AI tools", observed_at=observed)
    patterns = store.patterns_summary()

    assert patterns["dataset"]["videosTracked"] == 3
    assert patterns["topics"][0]["topic"] == "AI tools"
    assert patterns["topics"][0]["videos"] == 3
    assert patterns["contentTypes"][0]["type"] == "Short"
    assert patterns["contentTypes"][0]["videos"] == 3
    beginners = next(
        signal for signal in patterns["titleSignals"] if signal["term"] == "beginners"
    )
    tools_beginners = next(
        signal for signal in patterns["titleSignals"] if signal["term"] == "tools beginners"
    )
    assert beginners["channels"] == 3
    assert tools_beginners["channels"] == 2
    ai_tools = next(
        signal for signal in patterns["titleSignals"] if signal["term"] == "ai tools"
    )
    assert ai_tools["channels"] == 3



def test_title_signals_remove_seo_noise_and_require_multiple_channels(tmp_path):
    db = tmp_path / "christina_lab.sqlite3"
    store = SnapshotStore(f"sqlite:///{db}")
    observed = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)

    rows = [
        ("v1", "channel-a", "Copy Trading Journal #viral #shortsfeed #trending #dubai"),
        ("v2", "channel-b", "My #copytrading Journal #explore #ytshorts"),
        # One channel repeating its own phrase should not create a market signal.
        ("v3", "channel-c", "Private Edge System"),
        ("v4", "channel-c", "Private Edge System Explained"),
    ]
    for video_id, channel_id, title in rows:
        store.record_snapshots(
            [
                _video(
                    video_id=video_id,
                    channel_id=channel_id,
                    title=title,
                    published_at=observed - timedelta(hours=6),
                    content_type="Long-form",
                    views=1000,
                )
            ],
            observed_at=observed,
            min_interval_minutes=0,
        )

    _record_candidate_analyses(
        store, [video_id for video_id, _, _ in rows], observed, topic="copy trading"
    )

    patterns = store.patterns_summary()
    terms = {signal["term"]: signal for signal in patterns["titleSignals"]}

    assert "copy trading" in terms
    assert terms["copy trading"]["channels"] == 2
    assert "trading journal" in terms
    assert terms["trading journal"]["channels"] == 2

    for noisy in ["viral", "shortsfeed", "trending", "explore", "ytshorts", "dubai"]:
        assert noisy not in terms

    assert "private edge" not in terms
    assert "trading" not in terms


def test_content_type_patterns_include_growth_distribution(tmp_path):
    db = tmp_path / "christina_lab.sqlite3"
    store = SnapshotStore(f"sqlite:///{db}")
    published = datetime(2026, 9, 19, 10, 0, tzinfo=timezone.utc)
    first = datetime(2026, 9, 19, 11, 0, tzinfo=timezone.utc)
    second = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)

    # One-hour growth rates: 0, 100, 300, 900 views/hour.
    growth_rates = [0, 100, 300, 900]
    for index, rate in enumerate(growth_rates, start=1):
        video_id = f"growth-dist-{index}"
        base = _video(
            video_id=video_id,
            channel_id=f"channel-{index}",
            title=f"Pattern Video {index}",
            published_at=published,
            content_type="Short",
            views=1000,
        )
        store.record_snapshots([base], observed_at=first, min_interval_minutes=0)
        base["views"] = 1000 + rate
        store.record_snapshots([base], observed_at=second, min_interval_minutes=0)

    patterns = store.patterns_summary()
    short = next(row for row in patterns["contentTypes"] if row["type"] == "Short")

    assert short["growthSampleSize"] == 4
    assert short["positiveGrowthSampleSize"] == 3
    assert short["positiveGrowthShare"] == 75.0
    assert short["medianActualGrowthPerHour"] == 200.0
    # Linear 75th percentile between 300 and 900 = 450.
    assert short["topQuartileActualGrowthPerHour"] == 450.0



def test_title_signal_specificity_filters_common_words_and_locations(tmp_path):
    db = tmp_path / "christina_lab.sqlite3"
    store = SnapshotStore(f"sqlite:///{db}")
    observed = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)

    rows = [
        ("v1", "channel-a", "How to Build a Copy Trading Journal in India"),
        ("v2", "channel-b", "The Copy Trading Journal Setup for a New Trader"),
        ("v3", "channel-c", "Real Gold Strategy Setup for Day Trading"),
        ("v4", "channel-d", "Gold Strategy Setup That Actually Works"),
    ]
    for video_id, channel_id, title in rows:
        store.record_snapshots(
            [
                _video(
                    video_id=video_id,
                    channel_id=channel_id,
                    title=title,
                    published_at=observed - timedelta(hours=6),
                    content_type="Long-form",
                    views=1000,
                )
            ],
            observed_at=observed,
            min_interval_minutes=0,
        )

    _record_candidate_analyses(
        store, [video_id for video_id, _, _ in rows], observed, topic="trading ideas"
    )

    patterns = store.patterns_summary()
    terms = {signal["term"]: signal for signal in patterns["titleSignals"]}

    for noisy in [
        "for",
        "the",
        "how",
        "new",
        "real",
        "day",
        "india",
        "gold",
        "strategy",
        "setup",
        "trader",
    ]:
        assert noisy not in terms

    assert "copy trading" in terms
    assert "trading journal" in terms
    assert "gold strategy" in terms
    assert terms["copy trading"]["termType"] == "phrase"
    assert terms["gold strategy"]["termType"] == "phrase"


def test_title_signal_ranking_prefers_phrases_over_single_words(tmp_path):
    db = tmp_path / "christina_lab.sqlite3"
    store = SnapshotStore(f"sqlite:///{db}")
    observed = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)

    rows = [
        ("v1", "channel-a", "Beginner Mistakes With Copy Trading"),
        ("v2", "channel-b", "Beginner Mistakes in Copy Trading"),
        ("v3", "channel-c", "Beginner Workflow Explained"),
        ("v4", "channel-d", "Beginner Guide"),
        ("v5", "channel-e", "Beginner Checklist"),
    ]
    for video_id, channel_id, title in rows:
        store.record_snapshots(
            [
                _video(
                    video_id=video_id,
                    channel_id=channel_id,
                    title=title,
                    published_at=observed - timedelta(hours=6),
                    content_type="Long-form",
                    views=1000,
                )
            ],
            observed_at=observed,
            min_interval_minutes=0,
        )

    _record_candidate_analyses(
        store, [video_id for video_id, _, _ in rows], observed, topic="beginner trading"
    )

    signals = store.patterns_summary()["titleSignals"]
    phrase_index = next(
        index for index, signal in enumerate(signals)
        if signal["term"] == "beginner mistakes"
    )
    word_index = next(
        index for index, signal in enumerate(signals)
        if signal["term"] == "beginner"
    )

    assert phrase_index < word_index
    assert signals[phrase_index]["termType"] == "phrase"
    assert signals[word_index]["termType"] == "specific-word"



def test_title_phrase_cleanup_normalizes_word_order_variants(tmp_path):
    db = tmp_path / "christina_lab.sqlite3"
    store = SnapshotStore(f"sqlite:///{db}")
    observed = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)

    rows = [
        ("v1", "channel-a", "Trading Forex With a Simple Setup"),
        ("v2", "channel-b", "Forex Trading Beginner Guide"),
    ]
    for video_id, channel_id, title in rows:
        store.record_snapshots(
            [
                _video(
                    video_id=video_id,
                    channel_id=channel_id,
                    title=title,
                    published_at=observed - timedelta(hours=6),
                    content_type="Long-form",
                    views=1000,
                )
            ],
            observed_at=observed,
            min_interval_minutes=0,
        )

    _record_candidate_analyses(
        store, [video_id for video_id, _, _ in rows], observed, topic="forex trading"
    )

    patterns = store.patterns_summary()
    terms = {signal["term"]: signal for signal in patterns["titleSignals"]}

    assert "forex trading" in terms
    assert terms["forex trading"]["videos"] == 2
    assert terms["forex trading"]["channels"] == 2
    assert "trading forex" not in terms


def test_title_phrase_cleanup_suppresses_known_filler_bigrams(tmp_path):
    db = tmp_path / "christina_lab.sqlite3"
    store = SnapshotStore(f"sqlite:///{db}")
    observed = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)

    rows = [
        ("v1", "channel-a", "Price Action Trading Setup"),
        ("v2", "channel-b", "Price Action Trading Guide"),
        ("v3", "channel-c", "Trading Motivation for Beginners"),
        ("v4", "channel-d", "Trading Motivation Daily"),
        ("v5", "channel-e", "Funny Comedy Trading Story"),
        ("v6", "channel-f", "Funny Comedy Market Story"),
        ("v7", "channel-g", "Trading Like a Professional"),
        ("v8", "channel-h", "Trading Like an Expert"),
    ]
    for video_id, channel_id, title in rows:
        store.record_snapshots(
            [
                _video(
                    video_id=video_id,
                    channel_id=channel_id,
                    title=title,
                    published_at=observed - timedelta(hours=6),
                    content_type="Long-form",
                    views=1000,
                )
            ],
            observed_at=observed,
            min_interval_minutes=0,
        )

    _record_candidate_analyses(
        store, [video_id for video_id, _, _ in rows], observed, topic="price action"
    )

    patterns = store.patterns_summary()
    terms = {signal["term"] for signal in patterns["titleSignals"]}

    assert "price action" in terms
    assert "trading setup" not in terms  # appears on only one channel here

    for filler in [
        "action trading",
        "trading motivation",
        "motivation trading",
        "funny comedy",
        "trading like",
        "action",
        "funny",
        "comedy",
        "like",
    ]:
        assert filler not in terms



def test_title_signals_exclude_baseline_only_channel_history(tmp_path):
    db = tmp_path / "christina_lab.sqlite3"
    store = SnapshotStore(f"sqlite:///{db}")
    observed = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)

    candidates = [
        ("candidate-1", "channel-a", "Copy Trading Journal Mistakes"),
        ("candidate-2", "channel-b", "Copy Trading Journal Setup"),
    ]
    baseline_only = [
        ("history-1", "channel-a", "Ganpati Bappa Celebration"),
        ("history-2", "channel-b", "Ganpati Bappa Festival"),
        ("history-3", "channel-c", "Ganpati Bappa Motivation"),
    ]

    for video_id, channel_id, title in candidates + baseline_only:
        store.record_snapshots(
            [
                _video(
                    video_id=video_id,
                    channel_id=channel_id,
                    title=title,
                    published_at=observed - timedelta(hours=6),
                    content_type="Long-form",
                    views=1000,
                )
            ],
            observed_at=observed,
            min_interval_minutes=0,
        )

    # Only Discover candidates receive analysis rows. The history videos exist
    # solely because Christina Lab fetched them to build channel baselines.
    _record_candidate_analyses(
        store,
        [video_id for video_id, _, _ in candidates],
        observed,
        topic="copy trading",
    )

    patterns = store.patterns_summary()
    terms = {signal["term"]: signal for signal in patterns["titleSignals"]}

    assert patterns["dataset"]["videosTracked"] == 5
    assert patterns["dataset"]["analyzedCandidates"] == 2
    assert patterns["dataset"]["creativePatternCandidates"] == 2
    assert "copy trading" in terms
    assert terms["copy trading"]["opportunitySampleSize"] == 2

    # These repeat across multiple baseline/history videos but must never become
    # a creative pattern because they were not Discover candidates.
    assert "ganpati bappa" not in terms



def test_saved_research_persists_creator_notes_and_latest_signals(tmp_path):
    db = tmp_path / "christina_lab.sqlite3"
    store = SnapshotStore(f"sqlite:///{db}")
    observed = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)
    published = observed - timedelta(hours=4)

    video = _video(
        video_id="research-1",
        channel_id="channel-a",
        title="AI Tools Workflow",
        published_at=published,
        content_type="Long-form",
        views=4200,
        likes=320,
        comments=40,
        subscribers=10_000,
    )
    video["channel"] = "Creator A"
    video["thumbnail"] = "https://example.com/thumb.jpg"
    store.record_snapshots([video], observed_at=observed, min_interval_minutes=0)
    _record_candidate_analyses(store, ["research-1"], observed, topic="AI tools")

    saved = store.save_research(
        "research-1",
        why="Strong cross-channel signal.",
        adapt="Use the workflow on my own project.",
        angle="Show the failed version first.",
    )

    assert saved["videoId"] == "research-1"
    assert saved["title"] == "AI Tools Workflow"
    assert saved["channel"] == "Creator A"
    assert saved["topic"] == "AI tools"
    assert saved["why"] == "Strong cross-channel signal."
    assert saved["adapt"] == "Use the workflow on my own project."
    assert saved["angle"] == "Show the failed version first."
    assert saved["opportunity"] == 51

    saved_again = store.save_research("research-1", why="Updated reason.")
    assert saved_again["why"] == "Updated reason."
    assert saved_again["adapt"] == "Use the workflow on my own project."

    items = store.list_saved_research()
    assert len(items) == 1
    assert items[0]["ideaCount"] == 0

    assert store.remove_saved_research("research-1") is True
    assert store.list_saved_research() == []


def test_workflow_persists_idea_and_experiment_result(tmp_path):
    db = tmp_path / "christina_lab.sqlite3"
    store = SnapshotStore(f"sqlite:///{db}")
    observed = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)

    store.record_snapshots(
        [
            _video(
                video_id="source-1",
                channel_id="channel-a",
                title="Copy Trading Mistakes",
                published_at=observed - timedelta(hours=6),
                content_type="Long-form",
                views=5000,
            )
        ],
        observed_at=observed,
        min_interval_minutes=0,
    )
    store.save_research(
        "source-1",
        why="Good contradiction.",
        adapt="Use RiskDesk evidence.",
        angle="Focus on execution differences.",
    )

    idea = store.create_idea(
        source_video_id="source-1",
        title="Why Copying the Same Signal Gives Different Results",
        hook="Same signal. Different outcome.",
        topic="copy trading",
        content_type="Long-form",
        hypothesis="A contradiction hook should create curiosity.",
        status="Draft",
        priority="High",
    )

    assert idea["id"] == 1
    assert idea["sourceVideoId"] == "source-1"
    assert idea["status"] == "Draft"

    ready = store.update_idea(idea["id"], {"status": "Ready"})
    assert ready["status"] == "Ready"

    experiment = store.create_experiment(
        idea_id=idea["id"],
        name="Copy signal contradiction test",
        status="Ready",
    )
    assert experiment["ideaId"] == idea["id"]
    assert experiment["decision"] == "UNDECIDED"

    updated = store.update_experiment(
        experiment["id"],
        {
            "status": "Published",
            "publishedAt": "2026-09-19",
            "v24": 7420,
            "v7": 18640,
            "retention": 71.0,
            "subs": 38,
            "ctr": 8.4,
            "result": "Strong first 24 hours.",
            "decision": "GO",
            "lesson": "Contradiction framing worked.",
            "next": "Test the same structure on build in public.",
        },
    )

    assert updated["status"] == "Published"
    assert updated["v24"] == 7420
    assert updated["decision"] == "GO"
    assert updated["lesson"] == "Contradiction framing worked."

    # Publishing an experiment promotes its source idea to Published.
    assert store.get_idea(idea["id"])["status"] == "Published"

    workflow = store.workflow_summary()
    assert workflow["summary"]["savedResearch"] == 1
    assert workflow["summary"]["ideas"] == 1
    assert workflow["summary"]["experiments"] == 1
    assert workflow["summary"]["publishedExperiments"] == 1
    assert workflow["summary"]["decisions"]["GO"] == 1
    assert workflow["summary"]["average24hViews"] == 7420
    assert workflow["summary"]["averageSubscriberGain"] == 38.0

    signal = workflow["learningSignals"][0]
    assert signal["topic"] == "copy trading"
    assert signal["experiments"] == 1
    assert signal["GO"] == 1
    assert signal["avg24hViews"] == 7420
    assert signal["avgSubscriberGain"] == 38.0


def test_deleting_saved_research_does_not_delete_derived_idea(tmp_path):
    db = tmp_path / "christina_lab.sqlite3"
    store = SnapshotStore(f"sqlite:///{db}")
    observed = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)

    store.record_snapshots(
        [
            _video(
                video_id="source-2",
                published_at=observed - timedelta(hours=3),
                views=1200,
            )
        ],
        observed_at=observed,
        min_interval_minutes=0,
    )
    store.save_research("source-2")
    idea = store.create_idea(title="Independent idea", source_video_id="source-2")

    assert store.remove_saved_research("source-2") is True
    assert store.get_idea(idea["id"])["sourceVideoId"] == "source-2"

from backend.app.creator_agent import (
    _github_repo_parts,
    compact_youtube_sources,
    relevant_saved_research,
)


def test_github_repo_parts_accepts_public_github_urls():
    assert _github_repo_parts("https://github.com/KristineLio/christina-lab") == (
        "KristineLio",
        "christina-lab",
    )
    assert _github_repo_parts("github.com/KristineLio/christina-lab.git") == (
        "KristineLio",
        "christina-lab",
    )


def test_github_repo_parts_rejects_arbitrary_hosts():
    assert _github_repo_parts("https://example.com/KristineLio/christina-lab") is None
    assert _github_repo_parts("") is None


def test_relevant_saved_research_prefers_matching_creator_evidence():
    items = [
        {
            "title": "Building a Weather App",
            "topic": "coding projects",
            "why": "Good transformation story",
            "opportunity": 70,
            "views": 1000,
        },
        {
            "title": "Trading signal mistakes",
            "topic": "trading",
            "why": "Useful for RiskDesk",
            "opportunity": 95,
            "views": 9000,
        },
    ]

    result = relevant_saved_research(
        items,
        project="Weather App",
        topic="coding portfolio",
    )

    assert len(result) == 1
    assert result[0]["title"] == "Building a Weather App"


def test_compact_youtube_sources_keeps_only_agent_evidence_fields():
    videos = [
        {
            "id": "abc",
            "title": "I Built a Weather App",
            "channel": "Creator",
            "youtubeUrl": "https://www.youtube.com/watch?v=abc",
            "type": "Long-form",
            "views": 1234,
            "opportunity": 81,
            "outlier": 3.2,
            "engagement": 7.1,
            "topic": "weather app",
            "snapshotHistory": [{"views": 100}],
        }
    ]

    result = compact_youtube_sources(videos)

    assert result == [
        {
            "id": "abc",
            "title": "I Built a Weather App",
            "channel": "Creator",
            "url": "https://www.youtube.com/watch?v=abc",
            "type": "Long-form",
            "views": 1234,
            "opportunity": 81,
            "outlier": 3.2,
            "engagement": 7.1,
            "topic": "weather app",
        }
    ]

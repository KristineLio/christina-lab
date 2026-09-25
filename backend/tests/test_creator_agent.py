from backend.app.creator_agent import (
    IDEA_PRODUCTION_DOCS_SCHEMA,
    PACKAGE_SCHEMA,
    SAVED_RESEARCH_IDEA_SCHEMA,
    SHORT_MOMENTS_SCHEMA,
    SHORT_PACKAGE_SCHEMA,
    _github_repo_parts,
    _long_form_ai_scene_prompt_count,
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


def test_package_schema_includes_video_builder_manifest():
    assert "renderManifest" in PACKAGE_SCHEMA["properties"]
    manifest = PACKAGE_SCHEMA["properties"]["renderManifest"]
    assert set(manifest["required"]) == {"video", "scenes"}

    scene = manifest["properties"]["scenes"]["items"]
    assert "visualModes" in scene["properties"]
    assert "assets" in scene["properties"]
    assert "captureRequest" in scene["properties"]



def test_short_moments_schema_requires_three_grounded_moments():
    moments = SHORT_MOMENTS_SCHEMA["properties"]["moments"]
    assert moments["minItems"] == 3
    assert moments["maxItems"] == 3

    item = moments["items"]
    assert "frameTimeSeconds" in item["properties"]
    assert "mechanism" in item["properties"]
    assert "shortDirection" in item["properties"]


def test_short_package_schema_is_ai_studio_ready():
    variants = SHORT_PACKAGE_SCHEMA["properties"]["variants"]
    assert variants["minItems"] == 3
    assert variants["maxItems"] == 3

    item = variants["items"]
    assert "voiceover" in item["properties"]
    assert "onScreenText" in item["properties"]
    assert "shotPlan" in item["properties"]
    assert "aiStudioPrompt" in item["properties"]

    shots = item["properties"]["shotPlan"]
    assert shots["minItems"] == 3
    assert shots["maxItems"] == 3



def test_saved_research_idea_schema_keeps_format_as_user_constraint():
    props = SAVED_RESEARCH_IDEA_SCHEMA["properties"]
    assert "title" in props
    assert "hook" in props
    assert "angle" in props
    assert "audience" in props
    assert "hypothesis" in props
    assert "notes" in props
    assert "contentType" not in props



def test_idea_production_docs_schema_contains_video_prompt_and_photo_reference():
    props = IDEA_PRODUCTION_DOCS_SCHEMA["properties"]
    assert set(props) == {
        "script",
        "productionPlan",
        "videoPrompt",
        "photoReference",
    }
    assert set(IDEA_PRODUCTION_DOCS_SCHEMA["required"]) == set(props)



def test_long_form_ai_scene_prompt_count_scales_without_overfilling():
    assert _long_form_ai_scene_prompt_count(3) == 4
    assert _long_form_ai_scene_prompt_count(7) == 5
    assert _long_form_ai_scene_prompt_count(12) == 7
    assert _long_form_ai_scene_prompt_count(20) == 8

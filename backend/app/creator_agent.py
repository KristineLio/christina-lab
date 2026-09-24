from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib.parse import urlparse

import httpx


from .ai_provider import (
    AIProviderError,
    creator_agent_configured,
    creator_agent_model,
    creator_agent_provider,
    generate_structured,
    provider_status,
)


class CreatorAgentError(RuntimeError):
    pass


async def _structured_response(
    *,
    instructions: str,
    prompt: str,
    schema_name: str,
    schema: dict[str, Any],
    max_output_tokens: int = 6000,
):
    try:
        return await generate_structured(
            instructions=instructions,
            prompt=prompt,
            schema_name=schema_name,
            schema=schema,
            max_output_tokens=max_output_tokens,
        )
    except AIProviderError as exc:
        raise CreatorAgentError(str(exc)) from exc


def _github_repo_parts(repo_url: str | None) -> tuple[str, str] | None:
    value = (repo_url or "").strip()
    if not value:
        return None

    parsed = urlparse(value if "://" in value else "https://" + value)
    if parsed.hostname not in {"github.com", "www.github.com"}:
        return None

    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) < 2:
        return None

    owner = re.sub(r"[^A-Za-z0-9_.-]", "", parts[0])
    repo = re.sub(r"[^A-Za-z0-9_.-]", "", parts[1])
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not owner or not repo:
        return None
    return owner, repo


async def load_github_repo_context(repo_url: str | None) -> dict[str, Any]:
    parts = _github_repo_parts(repo_url)
    if not parts:
        return {
            "available": False,
            "reason": "No supported public GitHub repository URL was provided.",
        }

    owner, repo = parts
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Christina-Lab-Creator-Agent",
    }
    github_token = os.getenv("GITHUB_TOKEN", "").strip()
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    base = f"https://api.github.com/repos/{owner}/{repo}"
    try:
        async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
            meta_response = await client.get(base)
            if meta_response.status_code == 404:
                return {
                    "available": False,
                    "reason": "Repository not found or not public.",
                    "repository": f"{owner}/{repo}",
                }
            meta_response.raise_for_status()
            meta = meta_response.json()

            default_branch = meta.get("default_branch") or "main"

            readme_text = ""
            readme_response = await client.get(base + "/readme")
            if readme_response.is_success:
                readme_payload = readme_response.json()
                download_url = readme_payload.get("download_url")
                if download_url:
                    raw_response = await client.get(download_url)
                    if raw_response.is_success:
                        readme_text = raw_response.text[:14000]

            tree_files: list[str] = []
            tree_response = await client.get(
                base + f"/git/trees/{default_branch}",
                params={"recursive": "1"},
            )
            if tree_response.is_success:
                tree_payload = tree_response.json()
                tree_files = [
                    str(item.get("path"))
                    for item in tree_payload.get("tree", [])
                    if item.get("type") == "blob" and item.get("path")
                ][:220]

    except httpx.HTTPError as exc:
        return {
            "available": False,
            "reason": f"GitHub context could not be loaded: {exc}",
            "repository": f"{owner}/{repo}",
        }

    return {
        "available": True,
        "repository": f"{owner}/{repo}",
        "url": f"https://github.com/{owner}/{repo}",
        "description": meta.get("description") or "",
        "language": meta.get("language") or "",
        "stars": int(meta.get("stargazers_count") or 0),
        "defaultBranch": default_branch,
        "readme": readme_text,
        "files": tree_files,
    }


def relevant_saved_research(
    items: list[dict[str, Any]],
    *,
    project: str,
    topic: str = "",
    limit: int = 8,
) -> list[dict[str, Any]]:
    tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", f"{project} {topic}".lower())
        if len(token) >= 3
    }

    scored: list[tuple[int, dict[str, Any]]] = []
    for item in items:
        haystack = " ".join(
            str(item.get(key) or "")
            for key in ("title", "topic", "why", "adapt", "angle", "channel")
        ).lower()
        score = sum(1 for token in tokens if token in haystack)
        if score:
            scored.append((score, item))

    scored.sort(
        key=lambda pair: (
            pair[0],
            float(pair[1].get("opportunity") or 0),
            float(pair[1].get("views") or 0),
        ),
        reverse=True,
    )
    return [item for _, item in scored[:limit]]


def compact_youtube_sources(videos: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    rows = []
    for video in videos[:limit]:
        rows.append(
            {
                "id": str(video.get("id") or ""),
                "title": str(video.get("title") or "Untitled"),
                "channel": str(video.get("channel") or "Unknown"),
                "url": str(video.get("youtubeUrl") or ""),
                "type": str(video.get("type") or ""),
                "views": int(video.get("views") or 0),
                "opportunity": video.get("opportunity"),
                "outlier": video.get("outlier"),
                "engagement": video.get("engagement"),
                "topic": str(video.get("topic") or ""),
            }
        )
    return rows


ANGLE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "searchQuery": {"type": "string"},
        "sourceNotes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "whyUseful": {"type": "string"},
                    "useFor": {"type": "string"},
                    "caution": {"type": "string"},
                },
                "required": ["id", "whyUseful", "useFor", "caution"],
            },
        },
        "angles": {
            "type": "array",
            "minItems": 3,
            "maxItems": 3,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "hook": {"type": "string"},
                    "positioning": {"type": "string"},
                    "whyThisCouldWork": {"type": "string"},
                    "whatMakesItYours": {"type": "string"},
                    "sourceIds": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "id",
                    "title",
                    "hook",
                    "positioning",
                    "whyThisCouldWork",
                    "whatMakesItYours",
                    "sourceIds",
                ],
            },
        },
        "bestStartingAngleId": {"type": "string"},
    },
    "required": [
        "summary",
        "searchQuery",
        "sourceNotes",
        "angles",
        "bestStartingAngleId",
    ],
}


PACKAGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "idea": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "title": {"type": "string"},
                "hook": {"type": "string"},
                "topic": {"type": "string"},
                "contentType": {"type": "string"},
                "angle": {"type": "string"},
                "audience": {"type": "string"},
                "hypothesis": {"type": "string"},
                "notes": {"type": "string"},
            },
            "required": [
                "title",
                "hook",
                "topic",
                "contentType",
                "angle",
                "audience",
                "hypothesis",
                "notes",
            ],
        },
        "researchBrief": {"type": "string"},
        "script": {"type": "string"},
        "productionBlueprint": {"type": "string"},
        "renderManifest": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "video": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "aspectRatio": {"type": "string"},
                        "targetDurationSeconds": {"type": "integer"},
                        "style": {"type": "string"},
                        "narrationMode": {"type": "string"},
                        "captions": {"type": "boolean"},
                    },
                    "required": [
                        "aspectRatio",
                        "targetDurationSeconds",
                        "style",
                        "narrationMode",
                        "captions",
                    ],
                },
                "scenes": {
                    "type": "array",
                    "minItems": 6,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "id": {"type": "string"},
                            "start": {"type": "integer"},
                            "end": {"type": "integer"},
                            "narrativeJob": {"type": "string"},
                            "narrationIntent": {"type": "string"},
                            "visualModes": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "assets": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "onScreenText": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "captureRequest": {"type": "string"},
                        },
                        "required": [
                            "id",
                            "start",
                            "end",
                            "narrativeJob",
                            "narrationIntent",
                            "visualModes",
                            "assets",
                            "onScreenText",
                            "captureRequest",
                        ],
                    },
                },
            },
            "required": ["video", "scenes"],
        },
        "thumbnailConcept": {"type": "string"},
        "description": {"type": "string"},
        "cta": {"type": "string"},
    },
    "required": [
        "idea",
        "researchBrief",
        "script",
        "productionBlueprint",
        "renderManifest",
        "thumbnailConcept",
        "description",
        "cta",
    ],
}


SYSTEM_INSTRUCTIONS = """You are Christina Lab's Creator Agent.
Your job is to turn evidence into creator decisions and production material.

Channel identity:
- 'From Code to Career' documents a real journey from learning and coding to projects, AI, products, jobs, freelancing, and eventually earning from technical skills.
- The destination is intentionally open. Do not force the channel into only software tutorials, only AI, or only trading.
- Projects such as RiskDesk can appear first as technology/product stories, not as claims of trading expertise.

Rules:
- Use provided repository facts and research evidence. Never invent project features, metrics, tests, technologies, or personal history.
- If evidence is missing, label it as unknown or suggest footage/research needed.
- Use reference videos for pattern learning, not copying. Never reproduce another creator's script.
- Prefer a story: problem -> decision -> proof -> benefit.
- Keep the creator's decision human: research can recommend angles, but the user chooses before a full package is generated.
- Write production material in clear English and make it practical for a faceless video. Narration may be the creator's own voice or an AI-TTS draft unless the user's goal says otherwise.
- Treat bold packaging as a hypothesis to test, not as permission to invent evidence. The title/thumbnail may create curiosity, but the body must earn the click with real proof.
- Never fabricate screenshots, code, terminal results, test counts, recruiter reactions, hiring statistics, or product behavior.
"""


async def research_angles(
    *,
    project: str,
    goal: str,
    topic: str,
    content_type: str,
    repo_context: dict[str, Any],
    youtube_sources: list[dict[str, Any]],
    saved_research: list[dict[str, Any]],
) -> dict[str, Any]:
    prompt = f"""PROJECT
{project}

GOAL
{goal}

TOPIC / SEARCH SEED
{topic or project}

CONTENT TYPE
{content_type}

PUBLIC REPOSITORY CONTEXT
{json.dumps(repo_context, ensure_ascii=False)[:18000]}

YOUTUBE REFERENCE CANDIDATES
{json.dumps(youtube_sources, ensure_ascii=False)[:18000]}

RELEVANT SAVED CHRISTINA LAB RESEARCH
{json.dumps(saved_research, ensure_ascii=False)[:12000]}

Produce exactly three meaningfully different video angles.
First annotate which YouTube candidates are genuinely useful source material and what each should be studied for (title, hook, structure, proof, pacing, positioning, etc.).
Do not claim you watched a video or read a transcript; the YouTube evidence here is metadata unless saved notes explicitly say otherwise.
The bestStartingAngleId should identify the strongest starting option for this channel, but the user will still choose.
"""

    result, provider_attempt = await _structured_response(
        instructions=SYSTEM_INSTRUCTIONS,
        prompt=prompt,
        schema_name="creator_agent_angles",
        schema=ANGLE_SCHEMA,
        max_output_tokens=4500,
    )

    source_map = {source["id"]: source for source in youtube_sources if source.get("id")}
    enriched_sources = []
    for note in result.get("sourceNotes", []):
        source = source_map.get(str(note.get("id") or ""))
        if not source:
            continue
        enriched_sources.append({**source, **note})

    valid_ids = set(source_map)
    angles = []
    for angle in result.get("angles", []):
        angles.append(
            {
                **angle,
                "sourceIds": [
                    source_id
                    for source_id in angle.get("sourceIds", [])
                    if source_id in valid_ids
                ],
            }
        )

    return {
        "summary": result.get("summary", ""),
        "searchQuery": result.get("searchQuery", topic or project),
        "sourceMaterials": enriched_sources,
        "angles": angles,
        "bestStartingAngleId": result.get("bestStartingAngleId", ""),
        "repoContext": repo_context,
        "agentProvider": provider_attempt.provider,
        "agentModel": provider_attempt.model,
    }


async def generate_package(
    *,
    project: str,
    goal: str,
    topic: str,
    content_type: str,
    repo_context: dict[str, Any],
    chosen_angle: dict[str, Any],
    source_materials: list[dict[str, Any]],
    saved_research: list[dict[str, Any]],
) -> dict[str, Any]:
    prompt = f"""PROJECT
{project}

GOAL
{goal}

TOPIC
{topic or project}

CONTENT TYPE
{content_type}

USER-APPROVED ANGLE
{json.dumps(chosen_angle, ensure_ascii=False)}

PUBLIC REPOSITORY CONTEXT
{json.dumps(repo_context, ensure_ascii=False)[:18000]}

SELECTED SOURCE MATERIAL
{json.dumps(source_materials, ensure_ascii=False)[:18000]}

RELEVANT SAVED RESEARCH
{json.dumps(saved_research, ensure_ascii=False)[:12000]}

Create a complete first-draft production package.

RESEARCH BRIEF requirements:
- explain the chosen story and audience promise;
- list the source material and exactly what to study from each;
- clearly separate observed evidence from inference;
- include gaps that still need human verification.

SCRIPT requirements:
- retention-aware voice-over for a faceless video;
- opening proof quickly, no long channel intro;
- use timestamps/sections;
- include on-screen directions after each section;
- make technical detail support the story rather than become a tutorial;
- do not invent facts not present in the repo/research context.

PRODUCTION BLUEPRINT requirements:
Build a Video Builder-ready blueprint, not a generic checklist. It must include these sections in this order:

1. WORKING PACKAGING
- primary title, alternate titles, thumbnail text and visual;
- target length, aspect ratio, presentation style and channel frame.

2. VIEWER PROMISE
- state exactly what the click promises;
- explain what the video must prove to earn that click;
- add a guardrail against unsupported claims.

3. ASSET RULES
Classify every visual as one of:
- REAL_PROJECT_ASSET
- REAL_CAPTURE_REQUIRED
- GENERATED_GRAPHIC
- AI_BROLL_OPTIONAL
Prefer real project evidence over generated footage.
Only call a repository asset VERIFIED when its exact path exists in PUBLIC REPOSITORY CONTEXT. Never invent file paths.

4. VERIFIED / REQUIRED ASSETS
- list relevant screenshots, code files, tests and media paths that actually exist in repo context;
- separately list footage that still needs a truthful real capture.

5. SCENE-BY-SCENE PRODUCTION PLAN
Use a Markdown table with:
Scene | Time | Narrative Job | Narration Intent | Visual Source | Visual Direction | On-Screen Text
Create enough scenes for the requested duration. The first visual proof should appear within roughly 8 seconds for long-form content.

6. NARRATION DRAFT BY SCENE
- give the purpose and draft narration for each major scene;
- keep it consistent with the full SCRIPT;
- technical detail must support the story rather than become a tutorial.

7. EDITING & RETENTION RULES
- pacing, cut frequency, code readability, captions, music, section headers and rules for AI footage.

8. PROMISE / CLICKBAIT AUDIT
- quote/summarize the title + thumbnail promise;
- list concrete script obligations;
- mark which obligations are supported by repository/research evidence;
- flag anything that would require external evidence or real capture;
- do NOT automatically weaken bold packaging if the body can support it.

9. VIDEO BUILDER RENDER MANIFEST
- explain how the accompanying structured renderManifest should be used;
- every scene in renderManifest must correspond to the production plan;
- visualModes must use only: repo_asset, repo_file, real_capture_required, generated_graphic, ai_broll_optional;
- assets must be exact repo paths when repo-backed;
- captureRequest must be non-empty only when truthful live footage is required.

10. PRODUCTION CHECKLIST + UPLOAD PACKAGE + DEFINITION OF DONE
- what can be generated automatically;
- what needs real capture;
- human review checks;
- final title, thumbnail, description opening, CTA and tags;
- definition of done for a render-ready video.

RENDER MANIFEST requirements:
- produce a machine-readable scene plan for a future Christina Lab Video Builder;
- use seconds for start/end;
- scenes must be chronological, non-overlapping, and cover the intended video;
- never put invented repo paths in assets;
- if a visual cannot be sourced truthfully, mark it real_capture_required or generated_graphic instead of fabricating it.

The output should be directly useful as a production draft AND as input to an automated renderer, not a high-level outline.
"""

    result, provider_attempt = await _structured_response(
        instructions=SYSTEM_INSTRUCTIONS,
        prompt=prompt,
        schema_name="creator_agent_package",
        schema=PACKAGE_SCHEMA,
        max_output_tokens=14000,
    )
    return {
        **result,
        "_agentProvider": provider_attempt.provider,
        "_agentModel": provider_attempt.model,
    }

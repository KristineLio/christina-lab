from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib.parse import urlparse

import httpx


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_AGENT_MODEL = "gpt-5.6-luna"


class CreatorAgentError(RuntimeError):
    pass


def creator_agent_configured() -> bool:
    return bool(os.getenv("OPENAI_API_KEY", "").strip())


def creator_agent_model() -> str:
    return os.getenv("OPENAI_MODEL", DEFAULT_AGENT_MODEL).strip() or DEFAULT_AGENT_MODEL


def _extract_output_text(payload: dict[str, Any]) -> str:
    for item in payload.get("output", []) or []:
        if item.get("type") != "message":
            continue
        for part in item.get("content", []) or []:
            if part.get("type") == "output_text" and part.get("text"):
                return str(part["text"])
    value = payload.get("output_text")
    if value:
        return str(value)
    raise CreatorAgentError("The model returned no usable text output.")


async def _structured_response(
    *,
    instructions: str,
    prompt: str,
    schema_name: str,
    schema: dict[str, Any],
    max_output_tokens: int = 6000,
) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise CreatorAgentError("OPENAI_API_KEY is not configured.")

    body = {
        "model": creator_agent_model(),
        "instructions": instructions,
        "input": prompt,
        "max_output_tokens": max_output_tokens,
        "text": {
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "strict": True,
                "schema": schema,
            }
        },
    }

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                OPENAI_RESPONSES_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
    except httpx.HTTPError as exc:
        raise CreatorAgentError(f"Creator Agent could not reach the model API: {exc}") from exc

    if response.is_error:
        detail = f"Model API request failed (HTTP {response.status_code})."
        try:
            payload = response.json()
            detail = (
                payload.get("error", {}).get("message")
                or payload.get("message")
                or detail
            )
        except ValueError:
            pass
        raise CreatorAgentError(detail)

    payload = response.json()
    raw = _extract_output_text(payload)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CreatorAgentError("The model returned invalid structured output.") from exc


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
        "thumbnailConcept": {"type": "string"},
        "description": {"type": "string"},
        "cta": {"type": "string"},
    },
    "required": [
        "idea",
        "researchBrief",
        "script",
        "productionBlueprint",
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
- Write production material in clear English and make it practical for a faceless video using the creator's own voice.
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

    result = await _structured_response(
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
- target length and format;
- story structure and pacing table in Markdown;
- exact footage/screen-recording checklist;
- editing/retention notes;
- thumbnail concept;
- pre-publish checklist;
- upload package.

The output should be directly useful as a draft that the creator can edit, not a high-level outline.
"""

    return await _structured_response(
        instructions=SYSTEM_INSTRUCTIONS,
        prompt=prompt,
        schema_name="creator_agent_package",
        schema=PACKAGE_SCHEMA,
        max_output_tokens=10000,
    )

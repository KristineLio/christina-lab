from __future__ import annotations

import asyncio
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


def _timestamp_label(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


async def load_public_youtube_transcript(video_id: str) -> dict[str, Any]:
    clean_id = re.sub(r"[^A-Za-z0-9_-]", "", str(video_id or ""))[:32]
    if not clean_id:
        raise CreatorAgentError("A valid YouTube video ID is required.")

    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError as exc:
        raise CreatorAgentError(
            "Automatic transcript retrieval is not installed on this deployment."
        ) from exc

    def fetch():
        return YouTubeTranscriptApi().fetch(clean_id)

    try:
        transcript = await asyncio.to_thread(fetch)
    except Exception as exc:
        raise CreatorAgentError(
            "YouTube captions could not be loaded for this video. "
            "The creator may have disabled captions, the language may be unavailable, "
            "or YouTube may be blocking this server. Paste the timestamped transcript manually instead."
        ) from exc

    snippets = []
    for item in transcript:
        text = re.sub(r"\s+", " ", str(getattr(item, "text", "") or "")).strip()
        start = float(getattr(item, "start", 0) or 0)
        duration = float(getattr(item, "duration", 0) or 0)
        if not text:
            continue
        snippets.append(
            {
                "text": text,
                "start": start,
                "duration": duration,
            }
        )

    if not snippets:
        raise CreatorAgentError(
            "YouTube returned an empty transcript. Paste a timestamped transcript manually."
        )

    timestamped = "\n".join(
        f"{_timestamp_label(item['start'])} {item['text']}"
        for item in snippets
    )
    return {
        "videoId": clean_id,
        "language": str(getattr(transcript, "language", "") or ""),
        "languageCode": str(getattr(transcript, "language_code", "") or ""),
        "isGenerated": bool(getattr(transcript, "is_generated", False)),
        "snippetCount": len(snippets),
        "transcript": timestamped[:50000],
    }


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


IDEA_PRODUCTION_DOCS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "script": {"type": "string"},
        "productionPlan": {"type": "string"},
        "videoPrompt": {"type": "string"},
        "photoReference": {"type": "string"},
    },
    "required": [
        "script",
        "productionPlan",
        "videoPrompt",
        "photoReference",
    ],
}


SAVED_RESEARCH_IDEA_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string"},
        "hook": {"type": "string"},
        "topic": {"type": "string"},
        "angle": {"type": "string"},
        "audience": {"type": "string"},
        "hypothesis": {"type": "string"},
        "notes": {"type": "string"},
    },
    "required": [
        "title",
        "hook",
        "topic",
        "angle",
        "audience",
        "hypothesis",
        "notes",
    ],
}


SHORT_MOMENTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "moments": {
            "type": "array",
            "minItems": 3,
            "maxItems": 3,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "startSeconds": {"type": "number"},
                    "endSeconds": {"type": "number"},
                    "frameTimeSeconds": {"type": "number"},
                    "label": {"type": "string"},
                    "sourceParaphrase": {"type": "string"},
                    "mechanism": {"type": "string"},
                    "whyStrong": {"type": "string"},
                    "shortDirection": {"type": "string"},
                },
                "required": [
                    "id",
                    "startSeconds",
                    "endSeconds",
                    "frameTimeSeconds",
                    "label",
                    "sourceParaphrase",
                    "mechanism",
                    "whyStrong",
                    "shortDirection",
                ],
            },
        },
    },
    "required": ["summary", "moments"],
}


SHORT_PACKAGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "sourceMechanism": {"type": "string"},
        "variants": {
            "type": "array",
            "minItems": 3,
            "maxItems": 3,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "hook": {"type": "string"},
                    "voiceover": {"type": "string"},
                    "onScreenText": {"type": "string"},
                    "captionIdea": {"type": "string"},
                    "shotPlan": {
                        "type": "array",
                        "minItems": 3,
                        "maxItems": 3,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "start": {"type": "number"},
                                "end": {"type": "number"},
                                "visual": {"type": "string"},
                                "action": {"type": "string"},
                            },
                            "required": ["start", "end", "visual", "action"],
                        },
                    },
                    "aiStudioPrompt": {"type": "string"},
                },
                "required": [
                    "id",
                    "name",
                    "hook",
                    "voiceover",
                    "onScreenText",
                    "captionIdea",
                    "shotPlan",
                    "aiStudioPrompt",
                ],
            },
        },
    },
    "required": ["sourceMechanism", "variants"],
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


async def generate_idea_production_docs(
    *,
    idea: dict[str, Any],
    source_research: dict[str, Any] | None,
    platform: str,
) -> dict[str, Any]:
    content_type = "Short" if str(idea.get("type") or "") == "Short" else "Long-form"
    platform = str(platform or "").strip()

    prompt = f"""CHRISTINA LAB IDEA
{json.dumps(idea, ensure_ascii=False)[:14000]}

SOURCE SAVED RESEARCH
{json.dumps(source_research, ensure_ascii=False)[:14000] if source_research else "No saved source research is attached."}

IDEA CONTENT TYPE
{content_type}

USER-CHOSEN PRODUCTION PLATFORM
{platform}

Create four production-ready documents for this existing idea:
1. script
2. productionPlan
3. videoPrompt
4. photoReference

The idea's content type and the user's platform choice are HARD CONSTRAINTS. Do not change either.

PLATFORM RULES
- YouTube Shorts: vertical 9:16; clear first-second hook; concise explanation; readable captions; strong visual proof.
- TikTok: vertical 9:16; immediate conversational hook; fast creator pacing; natural phone-first visual language.
- Pinterest: vertical 9:16; clean, save-worthy, visually organized framing; strong readable text; useful/inspirational rather than chaotic pacing.
- Instagram: vertical 9:16; polished creator aesthetic; strong visual composition; clean text and transitions; engaging without looking like a generic ad.

CONTENT-TYPE RULES
If the idea is Short:
- script must be a complete short-form script sized for one publishable short;
- productionPlan must be a concise shot-by-shot plan;
- videoPrompt must describe the full short that can be generated/assembled from short AI clips;
- keep one core idea and one clear payoff.

If the idea is Long-form:
- script must be a structured long-form first draft or detailed narration outline appropriate to the idea;
- productionPlan must cover the full long-form video;
- videoPrompt must NOT pretend one generative-video call can create the whole long-form video;
- instead, videoPrompt should be for the strongest platform-compatible opening/hero/teaser scene that supports the long-form piece;
- clearly label which remaining long-form footage must be real capture, screen recording, B-roll, or separately generated scenes.

SCRIPT DOCUMENT
- Start with a heading that states Content type and Platform.
- Use the existing idea's title, hook, angle, audience and hypothesis as evidence.
- Do not invent project facts, results, metrics, income, tests, personal history, or outcomes.
- Make wording original; never copy the source creator's script or title.

PRODUCTION PLAN DOCUMENT
- Include platform, content type, target orientation, pacing, asset needs, shot/scene plan, on-screen text, edit notes, and definition of done.
- Separate VERIFIED/SUPPLIED material from REQUIRED CAPTURE and OPTIONAL AI-GENERATED material.
- When source research includes a thumbnail URL, label it only as an available SOURCE THUMBNAIL, not as proof that it is the correct frame for the new video.

VIDEO PROMPT DOCUMENT
- Must contain one clearly marked, copy-paste-ready AI Studio / Veo-style prompt.
- State Platform, 9:16 aspect ratio, suggested duration, tone, subject/action, environment, camera behavior, lighting, pacing, on-screen text, narration/voiceover intent, and ending.
- Tell the model to use a supplied reference image for composition/environment/continuity only.
- Do not instruct it to clone or impersonate an identifiable real person.
- If a person is needed, request an original/generic presenter unless the user has rights to reproduce the likeness.
- Do not request fake UI, fake data, fabricated screenshots, gibberish text, watermarks, or unsupported claims.

PHOTO REFERENCE DOCUMENT
This is a truthful reference-image brief, not a claim that an image was already generated.
Include:
- Reference goal
- Recommended source: REAL CAPTURE, USER-SUPPLIED IMAGE, or GENERATED REFERENCE
- Exact subject
- Framing/camera angle
- Environment/background
- Props/screens that may appear
- Lighting and mood
- Orientation: 9:16
- What must remain readable / what must not be fabricated
- A clearly marked IMAGE GENERATION PROMPT that can be used to create the still reference when no suitable real image exists
- A clearly marked REAL CAPTURE INSTRUCTION describing what screenshot/photo to take if a real project/source image is preferable

The output must be practical enough that the user can open Idea Documents, copy the video prompt, prepare the photo reference, and start producing immediately.
"""

    result, provider_attempt = await _structured_response(
        instructions=SYSTEM_INSTRUCTIONS + """
Idea Production Documents rules:
- The user's selected platform is a hard constraint.
- The idea's Short / Long-form format is a hard constraint.
- Produce executable production material, not generic brainstorming.
- A photo-reference document is a reference brief/capture-or-generation instruction unless a real image has actually been supplied.
- Never imply that an image, screenshot, project behavior, or performance result exists unless the supplied evidence proves it.
""",
        prompt=prompt,
        schema_name="creator_agent_idea_production_docs",
        schema=IDEA_PRODUCTION_DOCS_SCHEMA,
        max_output_tokens=9000,
    )

    return {
        **result,
        "_agentProvider": provider_attempt.provider,
        "_agentModel": provider_attempt.model,
    }


async def generate_idea_from_saved_research(
    *,
    saved_research: dict[str, Any],
    content_type: str,
) -> dict[str, Any]:
    normalized_type = "Short" if content_type == "Short" else "Long-form"
    prompt = f"""SAVED RESEARCH VIDEO
{json.dumps(saved_research, ensure_ascii=False)[:18000]}

USER-CHOSEN CONTENT TYPE
{normalized_type}

Create ONE original Christina Lab idea from this saved research item.

The content type above is a HARD CONSTRAINT. Do not change it or recommend a different format.

Use the saved video's title, topic, public performance metadata, and especially the user's Why / Adapt / Angle notes as evidence. The reference video is inspiration for structure, positioning, packaging, or storytelling mechanics — never a script to copy.

If content type is Short:
- make the concept focused enough for one short-form video;
- the hook should make sense immediately;
- center one clear idea, proof beat, transformation, mistake, reveal, or takeaway;
- do not turn it into a compressed long-form outline.

If content type is Long-form:
- give the idea enough narrative depth for a full video;
- prefer a clear story arc such as problem -> decision -> process/proof -> result/lesson;
- the hook and angle should support sustained curiosity, not just a one-line short.

Rules:
- Do not copy or closely paraphrase the source title or creator wording.
- Do not invent facts about Christina, her projects, results, income, metrics, tests, or experience.
- Treat the user's saved Adapt and Angle notes as strong intent signals.
- If the saved notes are sparse, keep unsupported specifics out rather than guessing.
- The idea should fit Christina Lab's From Code to Career direction where relevant.
- notes should briefly explain how the saved research informed this idea and what still needs real proof/capture.
"""

    result, provider_attempt = await _structured_response(
        instructions=SYSTEM_INSTRUCTIONS + """
Saved Research -> Idea rules:
- The user explicitly chooses Short or Long-form before generation. Obey that choice exactly.
- Convert research into an original creator idea, not a remake of the reference video.
- Preserve human intent from Why / Adapt / Angle notes.
""",
        prompt=prompt,
        schema_name="creator_agent_saved_research_idea",
        schema=SAVED_RESEARCH_IDEA_SCHEMA,
        max_output_tokens=3000,
    )
    return {
        **result,
        "_agentProvider": provider_attempt.provider,
        "_agentModel": provider_attempt.model,
    }


async def analyze_short_transcript(
    *,
    source_title: str,
    source_url: str,
    transcript: str,
    platform: str,
) -> dict[str, Any]:
    prompt = f"""SOURCE VIDEO
Title: {source_title}
URL: {source_url}

TARGET SHORT PLATFORM
{platform}

TIMESTAMPED TRANSCRIPT
{transcript[:50000]}

Find exactly three distinct moments with the strongest potential to inspire an ORIGINAL short-form video.

Requirements:
- The transcript is evidence. Do not claim visual details that are not stated in it.
- Prefer moments with a clear reveal, tension/open loop, useful mistake, transformation, surprising result, or compact insight.
- startSeconds/endSeconds/frameTimeSeconds must be grounded in timestamps that actually appear in the transcript. If a line has one timestamp only, use a reasonable short window around that timestamp without pretending the source supplied an exact end time.
- sourceParaphrase must paraphrase the source moment rather than reproduce the creator's distinctive wording.
- mechanism should explain the storytelling pattern abstractly, e.g. "proof first -> question -> explanation".
- shortDirection should explain how to make a new short from the mechanism without remaking the source.
- The three moments should be meaningfully different when the transcript supports it.
"""

    result, provider_attempt = await _structured_response(
        instructions=SYSTEM_INSTRUCTIONS + """
Source-to-Short rules:
- Learn from the source mechanism, never copy another creator's script.
- Avoid close paraphrase of distinctive source wording.
- Do not imitate a creator's identity, voice, or likeness.
- Prefer transferrable structure, pacing, tension, proof, and visual logic.
""",
        prompt=prompt,
        schema_name="creator_agent_short_moments",
        schema=SHORT_MOMENTS_SCHEMA,
        max_output_tokens=3500,
    )
    return {
        **result,
        "_agentProvider": provider_attempt.provider,
        "_agentModel": provider_attempt.model,
    }


async def generate_short_package(
    *,
    source_title: str,
    source_url: str,
    transcript: str,
    chosen_moment: dict[str, Any],
    platform: str,
    duration_seconds: int,
    has_reference_frame: bool,
) -> dict[str, Any]:
    prompt = f"""SOURCE VIDEO
Title: {source_title}
URL: {source_url}

TARGET
Platform: {platform}
Duration: {duration_seconds} seconds
Aspect ratio: 9:16
Reference frame supplied by user: {"yes" if has_reference_frame else "no"}

USER-SELECTED SOURCE MOMENT
{json.dumps(chosen_moment, ensure_ascii=False)}

NEARBY / FULL TRANSCRIPT EVIDENCE
{transcript[:50000]}

Create exactly three meaningfully different ORIGINAL short-video packages:
1. Proof First
2. Tension First
3. Original Reframe

For every variant:
- write new wording; do not quote or closely paraphrase the source creator;
- keep spoken copy realistic for {duration_seconds} seconds;
- make the first 1-2 seconds immediately understandable;
- create exactly three chronological shot-plan beats that fit inside {duration_seconds} seconds;
- the AI Studio prompt must be complete and paste-ready;
- if a reference image is supplied, tell AI Studio to use it for composition, environment, lighting, props, and continuity;
- do not instruct the model to clone or impersonate an identifiable person in the reference image;
- if a person is visible, request a generic/original presenter unless the uploader has rights to reproduce that likeness;
- preserve only supported factual ideas from the source;
- no fake UI, fake metrics, invented products, watermarks, gibberish text, or generic cinematic AI-ad language.

The AI Studio prompt must explicitly include:
- {duration_seconds}s duration and 9:16 vertical format;
- the variant's hook and original voiceover intent;
- on-screen text;
- 0-{min(2, duration_seconds)}s, middle, and final shot timing;
- reference-image handling;
- natural creator-style pacing and a clean ending suitable for looping.
"""

    result, provider_attempt = await _structured_response(
        instructions=SYSTEM_INSTRUCTIONS + """
Source-to-Short rules:
- The output is an original derivative concept, not a remake.
- Extract mechanism and transferable creative logic, not another creator's expression.
- Never imply the user owns or is the person shown in a reference image.
""",
        prompt=prompt,
        schema_name="creator_agent_short_package",
        schema=SHORT_PACKAGE_SCHEMA,
        max_output_tokens=6500,
    )
    return {
        **result,
        "_agentProvider": provider_attempt.provider,
        "_agentModel": provider_attempt.model,
    }


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

from __future__ import annotations

import asyncio
import importlib.util
import os
import re
import shutil
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any

from .creator_agent import CreatorAgentError, analyze_short_transcript, creator_agent_configured

CLIP_ROOT = Path(os.getenv("CLIP_LAB_ROOT", Path(tempfile.gettempdir()) / "christina-lab-clips"))
CLIP_ROOT.mkdir(parents=True, exist_ok=True)

DEFAULT_MODEL = os.getenv("CLIP_WHISPER_MODEL", "tiny").strip() or "tiny"
MAX_UPLOAD_BYTES = int(os.getenv("CLIP_MAX_UPLOAD_BYTES", str(500 * 1024 * 1024)))

_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()
_WHISPER_MODEL = None
_WHISPER_LOCK = threading.Lock()


def clip_lab_status() -> dict[str, Any]:
    ffmpeg_path = shutil.which("ffmpeg")
    ffprobe_path = shutil.which("ffprobe")
    whisper_installed = importlib.util.find_spec("faster_whisper") is not None
    return {
        "configured": bool(ffmpeg_path and ffprobe_path and whisper_installed),
        "ffmpeg": bool(ffmpeg_path),
        "ffprobe": bool(ffprobe_path),
        "whisperInstalled": whisper_installed,
        "whisperModel": DEFAULT_MODEL,
        "maxUploadBytes": MAX_UPLOAD_BYTES,
    }


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": job["id"],
        "status": job["status"],
        "stage": job["stage"],
        "progress": job["progress"],
        "message": job.get("message", ""),
        "error": job.get("error", ""),
        "originalName": job.get("originalName", ""),
        "clipCount": job.get("clipCount", 3),
        "minSeconds": job.get("minSeconds", 20),
        "maxSeconds": job.get("maxSeconds", 45),
        "burnCaptions": job.get("burnCaptions", True),
        "language": job.get("language", ""),
        "durationSeconds": job.get("durationSeconds"),
        "selectionMethod": job.get("selectionMethod", ""),
        "clips": job.get("clips", []),
    }


def create_clip_job(*, workspace_id: str, source_path: Path, original_name: str, clip_count: int,
                    min_seconds: int, max_seconds: int, burn_captions: bool) -> dict[str, Any]:
    job_id = uuid.uuid4().hex
    job_dir = CLIP_ROOT / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    target_path = job_dir / ("source" + source_path.suffix.lower())
    shutil.move(str(source_path), target_path)

    job = {
        "id": job_id,
        "workspaceId": workspace_id,
        "jobDir": str(job_dir),
        "sourcePath": str(target_path),
        "originalName": original_name,
        "clipCount": max(1, min(int(clip_count), 3)),
        "minSeconds": max(8, int(min_seconds)),
        "maxSeconds": max(int(min_seconds), min(int(max_seconds), 90)),
        "burnCaptions": bool(burn_captions),
        "status": "queued",
        "stage": "queued",
        "progress": 0,
        "message": "Queued for transcription.",
        "error": "",
        "clips": [],
    }
    with _JOBS_LOCK:
        _JOBS[job_id] = job
    return _public_job(job)


def get_clip_job(job_id: str, *, workspace_id: str) -> dict[str, Any] | None:
    with _JOBS_LOCK:
        job = _JOBS.get(str(job_id))
        if not job or job.get("workspaceId") != workspace_id:
            return None
        return _public_job(job)


def clip_output_path(job_id: str, filename: str, *, workspace_id: str) -> Path | None:
    clean = Path(str(filename or "")).name
    if not clean:
        return None
    with _JOBS_LOCK:
        job = _JOBS.get(str(job_id))
        if not job or job.get("workspaceId") != workspace_id:
            return None
        job_dir = Path(job["jobDir"]).resolve()
    candidate = (job_dir / clean).resolve()
    if job_dir not in candidate.parents:
        return None
    if not candidate.exists() or not candidate.is_file():
        return None
    return candidate


def _update(job_id: str, **changes: Any) -> None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job:
            job.update(changes)


def _whisper_model():
    global _WHISPER_MODEL
    if _WHISPER_MODEL is not None:
        return _WHISPER_MODEL
    with _WHISPER_LOCK:
        if _WHISPER_MODEL is not None:
            return _WHISPER_MODEL
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError("Clip Lab transcription is not installed. Install backend/requirements-video.txt.") from exc
        _WHISPER_MODEL = WhisperModel(DEFAULT_MODEL, device="cpu", compute_type="int8")
    return _WHISPER_MODEL


def _probe_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return max(0.0, float(result.stdout.strip() or 0))


def _transcribe(path: Path) -> tuple[list[dict[str, Any]], str]:
    model = _whisper_model()
    segments_iter, info = model.transcribe(str(path), beam_size=3, vad_filter=True, word_timestamps=False)
    segments: list[dict[str, Any]] = []
    for item in segments_iter:
        text = re.sub(r"\s+", " ", str(item.text or "")).strip()
        if not text:
            continue
        start = float(item.start or 0)
        end = float(item.end or start)
        if end <= start:
            continue
        segments.append({"start": start, "end": end, "text": text})
    return segments, str(getattr(info, "language", "") or "")


def _timestamp_label(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def _timestamped_transcript(segments: list[dict[str, Any]]) -> str:
    return "\n".join(f"{_timestamp_label(row['start'])} {row['text']}" for row in segments)[:50000]


def _window_score(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return -1000.0
    text = " ".join(row["text"] for row in rows).strip()
    lower = text.lower()
    duration = max(1.0, rows[-1]["end"] - rows[0]["start"])
    words = re.findall(r"\b[\w'-]+\b", text)
    score = min(len(words), 90) / 8.0
    for term in ("but ", "why ", "how ", "never ", "mistake", "problem", "actually", "instead",
                 "the reason", "if you", "what happens", "here's", "here is", "the truth",
                 "most people", "the biggest", "i realized", "i learned"):
        if term in lower[:220]:
            score += 3.0
    for term in ("because", "so ", "which means", "that's why", "that is why",
                 "the result", "it worked", "what changed", "the point", "finally"):
        if term in lower:
            score += 1.5
    if "?" in text:
        score += 2.0
    if re.search(r"\b\d+(?:\.\d+)?%?\b", text):
        score += 1.0
    if 18 <= duration <= 45:
        score += 3.0
    elif duration > 60:
        score -= 3.0
    if len(words) < 35:
        score -= 4.0
    filler = sum(lower.count(x) for x in (" um ", " uh ", " you know ", " like "))
    score -= min(filler, 5) * 0.5
    return score


def _fallback_moments(segments: list[dict[str, Any]], *, count: int,
                      min_seconds: int, max_seconds: int) -> list[dict[str, Any]]:
    candidates: list[tuple[float, int, int]] = []
    for start_idx in range(len(segments)):
        start = segments[start_idx]["start"]
        end_idx = start_idx
        while end_idx < len(segments):
            end = segments[end_idx]["end"]
            duration = end - start
            if duration >= min_seconds:
                candidates.append((_window_score(segments[start_idx:end_idx + 1]), start_idx, end_idx))
            if duration >= max_seconds:
                break
            end_idx += 1

    candidates.sort(reverse=True, key=lambda item: item[0])
    chosen: list[tuple[float, int, int]] = []
    for candidate in candidates:
        _, a, b = candidate
        c_start, c_end = segments[a]["start"], segments[b]["end"]
        overlaps = False
        for _, x, y in chosen:
            p_start, p_end = segments[x]["start"], segments[y]["end"]
            overlap = max(0.0, min(c_end, p_end) - max(c_start, p_start))
            shorter = max(1.0, min(c_end - c_start, p_end - p_start))
            if overlap / shorter > 0.45:
                overlaps = True
                break
        if not overlaps:
            chosen.append(candidate)
        if len(chosen) >= count:
            break

    if not chosen and segments:
        chosen = [(0.0, 0, min(len(segments) - 1, 4))]

    moments = []
    for rank, (score, a, b) in enumerate(chosen, start=1):
        rows = segments[a:b + 1]
        text = " ".join(row["text"] for row in rows)
        moments.append({
            "id": f"fallback-{rank}",
            "startSeconds": float(rows[0]["start"]),
            "endSeconds": float(rows[-1]["end"]),
            "frameTimeSeconds": float(rows[0]["start"] + min(2.0, (rows[-1]["end"] - rows[0]["start"]) / 2)),
            "label": f"Strong moment {rank}",
            "sourceParaphrase": text[:500],
            "mechanism": "Self-contained high-signal passage",
            "whyStrong": "Selected from transcript structure and hook/payoff heuristics.",
            "shortDirection": "Use the original passage as the clip from the creator's own uploaded video.",
            "_score": round(score, 2),
        })
    return moments[:count]


def _segment_window(segments: list[dict[str, Any]], *, requested_start: float, requested_end: float,
                    min_seconds: int, max_seconds: int, total_duration: float) -> tuple[float, float]:
    if not segments:
        start = max(0.0, requested_start)
        end = min(total_duration, max(requested_end, start + min_seconds))
        return start, min(end, start + max_seconds)

    nearest = min(range(len(segments)), key=lambda i: abs(float(segments[i]["start"]) - float(requested_start)))
    start = max(0.0, float(segments[nearest]["start"]) - 0.15)
    target_end = max(float(requested_end), start + min_seconds)

    end = float(segments[nearest]["end"])
    idx = nearest
    while idx + 1 < len(segments) and end < target_end:
        next_end = float(segments[idx + 1]["end"])
        if next_end - start > max_seconds:
            break
        idx += 1
        end = next_end

    end = min(total_duration, max(end, start + min_seconds))
    end = min(end, start + max_seconds)
    if end <= start:
        end = min(total_duration, start + min_seconds)
    return round(start, 3), round(end, 3)


def _segments_for_clip(segments: list[dict[str, Any]], start: float, end: float) -> list[dict[str, Any]]:
    return [row for row in segments if float(row["end"]) > start and float(row["start"]) < end]


def _srt_time(seconds: float) -> str:
    millis = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(millis, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, ms = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def _write_srt(path: Path, rows: list[dict[str, Any]], *, clip_start: float, clip_end: float) -> None:
    blocks = []
    index = 1
    for row in rows:
        start = max(0.0, float(row["start"]) - clip_start)
        end = min(clip_end - clip_start, float(row["end"]) - clip_start)
        if end <= start:
            continue
        text = re.sub(r"\s+", " ", str(row["text"])).strip()
        if not text:
            continue
        blocks.append(f"{index}\n{_srt_time(start)} --> {_srt_time(end)}\n{text}\n")
        index += 1
    path.write_text("\n".join(blocks), encoding="utf-8")


def _ffmpeg_subtitle_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def _render_clip(*, source: Path, output: Path, start: float, end: float, srt_path: Path | None) -> None:
    duration = max(0.1, end - start)
    video_filter = "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280"
    if srt_path is not None and srt_path.exists() and srt_path.stat().st_size:
        video_filter += (
            ",subtitles='" + _ffmpeg_subtitle_path(srt_path)
            + "':force_style='FontName=Arial,FontSize=20,PrimaryColour=&H00FFFFFF,"
            "OutlineColour=&H00000000,BorderStyle=1,Outline=3,Shadow=0,Alignment=2,MarginV=85'"
        )

    subprocess.run(
        ["ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", str(source), "-t", f"{duration:.3f}",
         "-vf", video_filter, "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
         "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(output)],
        capture_output=True, text=True, check=True,
    )


async def process_clip_job(job_id: str) -> None:
    with _JOBS_LOCK:
        job = dict(_JOBS.get(job_id) or {})
    if not job:
        return

    source = Path(job["sourcePath"])
    clip_count = int(job["clipCount"])
    min_seconds = int(job["minSeconds"])
    max_seconds = int(job["maxSeconds"])

    try:
        _update(job_id, status="processing", stage="probing", progress=5, message="Reading video duration.")
        duration = await asyncio.to_thread(_probe_duration, source)
        _update(job_id, durationSeconds=round(duration, 2))

        _update(job_id, stage="transcribing", progress=15,
                message=f"Transcribing locally with Whisper {DEFAULT_MODEL}.")
        segments, language = await asyncio.to_thread(_transcribe, source)
        if not segments:
            raise RuntimeError("No speech could be transcribed from this video.")
        _update(job_id, language=language, progress=45)

        transcript = _timestamped_transcript(segments)
        moments: list[dict[str, Any]] = []
        selection_method = "local-heuristic"

        if creator_agent_configured():
            _update(job_id, stage="selecting", progress=52,
                    message="Creator Agent is choosing the strongest moments.")
            try:
                result = await analyze_short_transcript(
                    source_title=job.get("originalName") or "Uploaded long-form video",
                    source_url="local-upload",
                    transcript=transcript,
                    platform="TikTok / Instagram Reels / YouTube Shorts",
                )
                moments = list(result.get("moments") or [])[:clip_count]
                if moments:
                    selection_method = "creator-agent"
            except CreatorAgentError:
                moments = []

        if not moments:
            moments = _fallback_moments(
                segments, count=clip_count, min_seconds=min_seconds, max_seconds=max_seconds
            )
        if not moments:
            raise RuntimeError("Could not identify clip-worthy transcript moments.")

        _update(job_id, stage="rendering", progress=60,
                message=f"Rendering {len(moments)} vertical clips.", selectionMethod=selection_method)

        rendered = []
        job_dir = Path(job["jobDir"])
        for index, moment in enumerate(moments, start=1):
            start, end = _segment_window(
                segments,
                requested_start=float(moment.get("startSeconds") or 0),
                requested_end=float(moment.get("endSeconds") or 0),
                min_seconds=min_seconds, max_seconds=max_seconds, total_duration=duration,
            )
            rows = _segments_for_clip(segments, start, end)
            output_name = f"clip-{index:02d}.mp4"
            srt_name = f"clip-{index:02d}.srt"
            output = job_dir / output_name
            srt = job_dir / srt_name
            _write_srt(srt, rows, clip_start=start, clip_end=end)

            await asyncio.to_thread(
                _render_clip, source=source, output=output, start=start, end=end,
                srt_path=srt if bool(job["burnCaptions"]) else None,
            )

            excerpt = " ".join(row["text"] for row in rows)
            rendered.append({
                "id": f"clip-{index}",
                "rank": index,
                "label": str(moment.get("label") or f"Clip {index}"),
                "whyStrong": str(moment.get("whyStrong") or ""),
                "mechanism": str(moment.get("mechanism") or ""),
                "startSeconds": start,
                "endSeconds": end,
                "durationSeconds": round(end - start, 2),
                "transcript": excerpt[:1800],
                "videoFilename": output_name,
                "subtitleFilename": srt_name,
            })
            _update(job_id, progress=min(60 + round(index / len(moments) * 35), 95), clips=rendered)

        _update(job_id, status="completed", stage="completed", progress=100,
                message="Clips are ready.", clips=rendered, selectionMethod=selection_method)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "FFmpeg failed.")[-1600:]
        _update(job_id, status="failed", stage="failed", progress=100,
                error="Video rendering failed: " + detail,
                message="Clip Lab could not finish this job.")
    except Exception as exc:
        _update(job_id, status="failed", stage="failed", progress=100,
                error=str(exc), message="Clip Lab could not finish this job.")

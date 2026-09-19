from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from .metrics import (
    calculate_channel_baseline,
    calculate_video_metrics,
    format_duration,
    human_age,
    parse_youtube_duration,
)


class YouTubeAPIError(RuntimeError):
    pass


class YouTubeClient:
    BASE_URL = "https://www.googleapis.com/youtube/v3"
    BASELINE_UPLOADS_PER_CHANNEL = 12
    BASELINE_MIN_SAMPLE = 3
    PLAYLIST_CONCURRENCY = 6

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    async def _get(
        self,
        path: str,
        params: dict,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> dict:
        params = {**params, "key": self.api_key}

        if client is None:
            async with httpx.AsyncClient(timeout=20.0) as owned_client:
                return await self._get(path, params, client=owned_client)

        response = await client.get(f"{self.BASE_URL}/{path}", params=params)
        if response.is_error:
            detail = "YouTube API request failed"
            try:
                payload = response.json()
                detail = payload.get("error", {}).get("message", detail)
            except ValueError:
                pass
            raise YouTubeAPIError(f"{detail} (HTTP {response.status_code})")

        return response.json()

    async def discover(
        self,
        *,
        query: str,
        max_results: int = 25,
        published_after_days: int = 7,
    ) -> dict:
        now = datetime.now(timezone.utc)
        published_after = now - timedelta(days=published_after_days)

        async with httpx.AsyncClient(timeout=20.0) as client:
            search_payload = await self._get(
                "search",
                {
                    "part": "snippet",
                    "type": "video",
                    "q": query,
                    "maxResults": max_results,
                    "order": "date",
                    "publishedAfter": published_after.isoformat().replace("+00:00", "Z"),
                },
                client=client,
            )

            video_ids = [
                item.get("id", {}).get("videoId")
                for item in search_payload.get("items", [])
                if item.get("id", {}).get("videoId")
            ]
            if not video_ids:
                return {
                    "query": query,
                    "count": 0,
                    "videos": [],
                    "baselineMeta": self._baseline_meta(),
                }

            videos_payload = await self._get(
                "videos",
                {
                    "part": "snippet,statistics,contentDetails",
                    "id": ",".join(video_ids),
                    "maxResults": max_results,
                },
                client=client,
            )

            channel_ids = sorted(
                {
                    item.get("snippet", {}).get("channelId")
                    for item in videos_payload.get("items", [])
                    if item.get("snippet", {}).get("channelId")
                }
            )

            channel_profiles: dict[str, dict] = {}
            if channel_ids:
                channels_payload = await self._get(
                    "channels",
                    {
                        "part": "statistics,contentDetails",
                        "id": ",".join(channel_ids),
                        "maxResults": min(len(channel_ids), 50),
                    },
                    client=client,
                )
                for channel in channels_payload.get("items", []):
                    stats = channel.get("statistics", {})
                    content_details = channel.get("contentDetails", {})
                    hidden = bool(stats.get("hiddenSubscriberCount"))
                    subscribers = None if hidden else _to_int(stats.get("subscriberCount"))
                    uploads_playlist = (
                        content_details.get("relatedPlaylists", {}).get("uploads")
                    )
                    channel_profiles[channel["id"]] = {
                        "subscribers": subscribers,
                        "uploadsPlaylist": uploads_playlist,
                    }

            candidate_items = videos_payload.get("items", [])
            candidate_samples = {
                item["id"]: _video_sample(item)
                for item in candidate_items
                if item.get("id")
            }

            channel_upload_ids = await self._fetch_recent_upload_ids(
                channel_profiles=channel_profiles,
                client=client,
            )

            baseline_sample_by_id = dict(candidate_samples)
            baseline_ids = {
                video_id
                for ids in channel_upload_ids.values()
                for video_id in ids
                if video_id not in baseline_sample_by_id
            }

            for chunk in _chunks(sorted(baseline_ids), 50):
                payload = await self._get(
                    "videos",
                    {
                        "part": "statistics,contentDetails",
                        "id": ",".join(chunk),
                        "maxResults": len(chunk),
                    },
                    client=client,
                )
                for item in payload.get("items", []):
                    if item.get("id"):
                        baseline_sample_by_id[item["id"]] = _video_sample(item)

        results = []
        for item in candidate_items:
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            content = item.get("contentDetails", {})

            published_raw = snippet.get("publishedAt")
            if not published_raw:
                continue
            published_at = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))

            views = _to_int(stats.get("viewCount"))
            likes = _to_int(stats.get("likeCount"))
            comments = _to_int(stats.get("commentCount"))
            channel_id = snippet.get("channelId")
            profile = channel_profiles.get(channel_id, {})
            subscribers = profile.get("subscribers")

            duration_seconds = parse_youtube_duration(content.get("duration", ""))
            video_type = _video_type(duration_seconds)
            derived = calculate_video_metrics(
                views=views,
                likes=likes,
                comments=comments,
                subscribers=subscribers,
                published_at=published_at,
                now=now,
            )

            recent_samples = [
                baseline_sample_by_id[video_id]
                for video_id in channel_upload_ids.get(channel_id, [])
                if video_id in baseline_sample_by_id
            ]
            baseline = calculate_channel_baseline(
                candidate_id=item["id"],
                candidate_views=views,
                candidate_type=video_type,
                samples=recent_samples,
                min_samples=self.BASELINE_MIN_SAMPLE,
            )

            thumbnails = snippet.get("thumbnails", {})
            thumbnail = (
                thumbnails.get("high", {}).get("url")
                or thumbnails.get("medium", {}).get("url")
                or thumbnails.get("default", {}).get("url")
            )

            video_id = item["id"]
            results.append(
                {
                    "id": video_id,
                    "source": "youtube",
                    "title": snippet.get("title", "Untitled"),
                    "channel": snippet.get("channelTitle", "Unknown channel"),
                    "channelId": channel_id,
                    "subs": subscribers,
                    "publishedAt": published_raw,
                    "published": human_age(published_at, now=now) + " ago",
                    "age": human_age(published_at, now=now),
                    "duration": format_duration(duration_seconds),
                    # YouTube's public API does not expose a definitive Shorts flag.
                    # <= 3 minutes is used as a coarse V1/V2 display heuristic.
                    "type": video_type,
                    "views": views,
                    "likes": likes,
                    "comments": comments,
                    **derived,
                    **baseline,
                    "topic": query,
                    "thumbnail": thumbnail,
                    "thumbAlt": f"YouTube thumbnail for {snippet.get('title', 'video')}",
                    "youtubeUrl": f"https://www.youtube.com/watch?v={video_id}",
                    "opportunity": None,
                    "momentum": None,
                }
            )

        results.sort(
            key=lambda video: (
                video["outlier"] is not None,
                video["outlier"] if video["outlier"] is not None else -1,
                video["viewsDay"],
            ),
            reverse=True,
        )
        return {
            "query": query,
            "count": len(results),
            "videos": results,
            "baselineMeta": self._baseline_meta(),
        }

    async def _fetch_recent_upload_ids(
        self,
        *,
        channel_profiles: dict[str, dict],
        client: httpx.AsyncClient,
    ) -> dict[str, list[str]]:
        semaphore = asyncio.Semaphore(self.PLAYLIST_CONCURRENCY)

        async def fetch_one(channel_id: str, playlist_id: str) -> tuple[str, list[str]]:
            async with semaphore:
                payload = await self._get(
                    "playlistItems",
                    {
                        "part": "contentDetails",
                        "playlistId": playlist_id,
                        # Request one extra so the candidate can be excluded
                        # while still leaving roughly 12 comparison uploads.
                        "maxResults": min(self.BASELINE_UPLOADS_PER_CHANNEL + 1, 50),
                    },
                    client=client,
                )
            ids = [
                item.get("contentDetails", {}).get("videoId")
                for item in payload.get("items", [])
                if item.get("contentDetails", {}).get("videoId")
            ]
            return channel_id, ids

        tasks = [
            fetch_one(channel_id, profile["uploadsPlaylist"])
            for channel_id, profile in channel_profiles.items()
            if profile.get("uploadsPlaylist")
        ]
        if not tasks:
            return {}

        pairs = await asyncio.gather(*tasks)
        return dict(pairs)

    def _baseline_meta(self) -> dict:
        return {
            "method": "median-views",
            "recentUploadsPerChannel": self.BASELINE_UPLOADS_PER_CHANNEL,
            "minimumSampleSize": self.BASELINE_MIN_SAMPLE,
            "formatPreference": "same-format-then-all-formats",
        }


def _video_type(duration_seconds: int) -> str:
    return "Short" if duration_seconds <= 180 else "Long-form"


def _video_sample(item: dict) -> dict:
    stats = item.get("statistics", {})
    content = item.get("contentDetails", {})
    duration_seconds = parse_youtube_duration(content.get("duration", ""))
    return {
        "id": item.get("id"),
        "views": _to_int(stats.get("viewCount")),
        "type": _video_type(duration_seconds),
    }


def _chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _to_int(value: str | int | None) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0

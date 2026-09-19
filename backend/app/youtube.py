from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from .metrics import (
    calculate_video_metrics,
    format_duration,
    human_age,
    parse_youtube_duration,
)


class YouTubeAPIError(RuntimeError):
    pass


class YouTubeClient:
    BASE_URL = "https://www.googleapis.com/youtube/v3"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    async def _get(self, path: str, params: dict) -> dict:
        params = {**params, "key": self.api_key}
        async with httpx.AsyncClient(timeout=20.0) as client:
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
        )

        video_ids = [
            item.get("id", {}).get("videoId")
            for item in search_payload.get("items", [])
            if item.get("id", {}).get("videoId")
        ]
        if not video_ids:
            return {"query": query, "count": 0, "videos": []}

        videos_payload = await self._get(
            "videos",
            {
                "part": "snippet,statistics,contentDetails",
                "id": ",".join(video_ids),
                "maxResults": max_results,
            },
        )

        channel_ids = sorted(
            {
                item.get("snippet", {}).get("channelId")
                for item in videos_payload.get("items", [])
                if item.get("snippet", {}).get("channelId")
            }
        )

        channel_stats: dict[str, int | None] = {}
        if channel_ids:
            channels_payload = await self._get(
                "channels",
                {
                    "part": "statistics",
                    "id": ",".join(channel_ids),
                    "maxResults": min(len(channel_ids), 50),
                },
            )
            for channel in channels_payload.get("items", []):
                stats = channel.get("statistics", {})
                hidden = bool(stats.get("hiddenSubscriberCount"))
                subscribers = None if hidden else _to_int(stats.get("subscriberCount"))
                channel_stats[channel["id"]] = subscribers

        results = []
        for item in videos_payload.get("items", []):
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
            subscribers = channel_stats.get(snippet.get("channelId"))

            duration_seconds = parse_youtube_duration(content.get("duration", ""))
            derived = calculate_video_metrics(
                views=views,
                likes=likes,
                comments=comments,
                subscribers=subscribers,
                published_at=published_at,
                now=now,
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
                    "channelId": snippet.get("channelId"),
                    "subs": subscribers,
                    "publishedAt": published_raw,
                    "published": human_age(published_at, now=now) + " ago",
                    "age": human_age(published_at, now=now),
                    "duration": format_duration(duration_seconds),
                    # YouTube's public API does not expose a definitive Shorts flag.
                    # <= 3 minutes is used only as a display heuristic for this V1.
                    "type": "Short" if duration_seconds <= 180 else "Long-form",
                    "views": views,
                    "likes": likes,
                    "comments": comments,
                    **derived,
                    "topic": query,
                    "thumbnail": thumbnail,
                    "thumbAlt": f"YouTube thumbnail for {snippet.get('title', 'video')}",
                    "youtubeUrl": f"https://www.youtube.com/watch?v={video_id}",
                    # Reserved for Milestone 2: channel-baseline outlier detection.
                    "baseline": None,
                    "outlier": None,
                    "opportunity": None,
                    "momentum": None,
                }
            )

        results.sort(key=lambda video: video["viewsDay"], reverse=True)
        return {"query": query, "count": len(results), "videos": results}


def _to_int(value: str | int | None) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0

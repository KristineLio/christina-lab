from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from .metrics import (
    calculate_channel_baseline,
    calculate_opportunity_score,
    calculate_video_metrics,
    format_duration,
    human_age,
    parse_youtube_duration,
)
from .storage import SnapshotStore


class YouTubeAPIError(RuntimeError):
    pass


class YouTubeClient:
    BASE_URL = "https://www.googleapis.com/youtube/v3"
    BASELINE_SCAN_UPLOADS_PER_CHANNEL = 30
    BASELINE_MAX_SAMPLES = 12
    BASELINE_MIN_SAMPLE = 3
    PLAYLIST_CONCURRENCY = 6
    VIDEO_PARTS = "snippet,statistics,contentDetails,liveStreamingDetails"

    def __init__(
        self,
        api_key: str,
        *,
        snapshot_store: SnapshotStore | None = None,
        workspace_id: str = "owner",
    ) -> None:
        self.api_key = api_key
        self.snapshot_store = snapshot_store or SnapshotStore()
        self.workspace_id = workspace_id

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
        mode: str = "trend",
    ) -> dict:
        now = datetime.now(timezone.utc)
        normalized_mode = "reference" if mode == "reference" else "trend"

        search_params = {
            "part": "snippet",
            "type": "video",
            "q": query,
            "maxResults": max_results,
            # Trend discovery is about recency. Reference discovery is about
            # finding useful precedents, so relevance is a better first pass.
            "order": "relevance" if normalized_mode == "reference" else "date",
        }
        if published_after_days > 0:
            published_after = now - timedelta(days=published_after_days)
            search_params["publishedAfter"] = published_after.isoformat().replace("+00:00", "Z")

        async with httpx.AsyncClient(timeout=20.0) as client:
            search_payload = await self._get(
                "search",
                search_params,
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
                    "mode": normalized_mode,
                    "count": 0,
                    "videos": [],
                    "baselineMeta": self._baseline_meta(),
                    "snapshotMeta": self.snapshot_store.stats(workspace_id=self.workspace_id),
                }

            videos_payload = await self._get(
                "videos",
                {
                    "part": self.VIDEO_PARTS,
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
                        "part": self.VIDEO_PARTS,
                        "id": ",".join(chunk),
                        "maxResults": len(chunk),
                    },
                    client=client,
                )
                for item in payload.get("items", []):
                    if item.get("id"):
                        baseline_sample_by_id[item["id"]] = _video_sample(item)

        # Record every candidate and recent-channel comparison video Christina Lab
        # has just observed. Re-running a search later creates another observation
        # (at most once every 15 minutes per video) and builds real growth history.
        snapshot_records = []
        for sample in baseline_sample_by_id.values():
            profile = channel_profiles.get(sample.get("channelId"), {})
            snapshot_records.append(
                {
                    **sample,
                    "subscribers": profile.get("subscribers"),
                }
            )
        inserted_snapshots = self.snapshot_store.record_snapshots(
            snapshot_records,
            observed_at=now,
            workspace_id=self.workspace_id,
        )

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
            video_type, live_status = _video_classification(item, duration_seconds)
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

            # Fallback estimate remains useful while the snapshot database is new.
            estimated_baseline = calculate_channel_baseline(
                candidate_id=item["id"],
                candidate_views=views,
                candidate_type=video_type,
                candidate_published_at=published_at,
                samples=recent_samples,
                min_samples=self.BASELINE_MIN_SAMPLE,
                max_samples=self.BASELINE_MAX_SAMPLES,
                now=now,
            )

            historical = self.snapshot_store.same_age_baseline(
                channel_id=channel_id,
                content_type=video_type,
                candidate_id=item["id"],
                target_age_hours=float(derived["ageHours"] or 0),
                min_samples=self.BASELINE_MIN_SAMPLE,
                max_samples=self.BASELINE_MAX_SAMPLES,
                workspace_id=self.workspace_id,
            )

            if historical.get("ready") and historical.get("baseline"):
                historical_baseline = int(historical["baseline"])
                baseline = {
                    "baseline": historical_baseline,
                    "outlier": round(views / historical_baseline, 2),
                    "baselineVelocity": None,
                    "candidateAgeHours": float(derived["ageHours"] or 0),
                    "baselineSampleSize": int(historical["sampleSize"]),
                    "baselineScope": "same-format-snapshots",
                    "baselineMethod": "historical-snapshot-median",
                    "baselineSource": "historical-snapshots",
                    "historicalTargetAgeHours": historical["targetAgeHours"],
                    "historicalToleranceHours": historical["toleranceHours"],
                }
            else:
                baseline = {
                    **estimated_baseline,
                    "baselineSource": "estimated-velocity",
                    "historicalSnapshotSampleSize": int(historical.get("sampleSize") or 0),
                    "historicalTargetAgeHours": historical.get("targetAgeHours"),
                    "historicalToleranceHours": historical.get("toleranceHours"),
                }

            thumbnails = snippet.get("thumbnails", {})
            thumbnail = (
                thumbnails.get("high", {}).get("url")
                or thumbnails.get("medium", {}).get("url")
                or thumbnails.get("default", {}).get("url")
            )

            opportunity = calculate_opportunity_score(
                views=views,
                subscribers=subscribers,
                views_day=float(derived["viewsDay"] or 0),
                engagement=float(derived["engagement"] or 0),
                views_sub=derived["viewsSub"],
                age_hours_value=float(derived["ageHours"] or 0),
                outlier=baseline["outlier"],
                baseline_sample_size=int(baseline["baselineSampleSize"] or 0),
                baseline_scope=str(baseline["baselineScope"]),
                baseline_method=str(baseline["baselineMethod"]),
                historical_snapshot_sample_size=int(
                    baseline.get("historicalSnapshotSampleSize")
                    or (
                        baseline["baselineSampleSize"]
                        if baseline["baselineMethod"] == "historical-snapshot-median"
                        else 0
                    )
                ),
                live_broadcast_content=snippet.get("liveBroadcastContent", "none"),
            )

            video_id = item["id"]
            snapshot_history = self.snapshot_store.video_snapshots(
                video_id,
                workspace_id=self.workspace_id,
            )
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
                    "durationSeconds": duration_seconds,
                    "type": video_type,
                    "liveStatus": live_status,
                    "views": views,
                    "likes": likes,
                    "comments": comments,
                    **derived,
                    **baseline,
                    **opportunity,
                    "topic": query,
                    "thumbnail": thumbnail,
                    "thumbAlt": f"YouTube thumbnail for {snippet.get('title', 'video')}",
                    "youtubeUrl": f"https://www.youtube.com/watch?v={video_id}",
                    "liveBroadcastContent": snippet.get("liveBroadcastContent", "none"),
                    "snapshotHistory": snapshot_history,
                    "snapshotCount": len(snapshot_history),
                    "momentum": None,
                }
            )

        analyzed_rows = self.snapshot_store.record_analyses(
            results,
            topic=query,
            observed_at=now,
            workspace_id=self.workspace_id,
        )

        results.sort(
            key=lambda video: (
                video["opportunity"],
                video["outlier"] if video["outlier"] is not None else -1,
                video["viewsDay"],
            ),
            reverse=True,
        )
        return {
            "query": query,
            "mode": normalized_mode,
            "count": len(results),
            "videos": results,
            "baselineMeta": self._baseline_meta(),
            "snapshotMeta": {
                **self.snapshot_store.stats(workspace_id=self.workspace_id),
                "insertedThisSearch": inserted_snapshots,
                "analysesStoredThisSearch": analyzed_rows,
            },
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
                        "maxResults": min(self.BASELINE_SCAN_UPLOADS_PER_CHANNEL + 1, 50),
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
            "method": "historical-snapshots-with-velocity-fallback",
            "historicalMethod": "historical-snapshot-median",
            "fallbackMethod": "median-age-adjusted-velocity",
            "scannedUploadsPerChannel": self.BASELINE_SCAN_UPLOADS_PER_CHANNEL,
            "maximumBaselineSamples": self.BASELINE_MAX_SAMPLES,
            "minimumSampleSize": self.BASELINE_MIN_SAMPLE,
            "formatPreference": "same-format-only-for-historical",
            "contentTypes": ["Short", "Long-form", "Livestream"],
        }


def _video_classification(item: dict, duration_seconds: int) -> tuple[str, str]:
    snippet = item.get("snippet", {})
    live_state = snippet.get("liveBroadcastContent", "none")
    live_details = item.get("liveStreamingDetails") or {}

    if live_state == "live":
        return "Livestream", "live"
    if live_state == "upcoming":
        return "Livestream", "upcoming"

    # Completed broadcasts normally keep liveStreamingDetails even after
    # liveBroadcastContent returns to "none".
    if live_details.get("actualStartTime") or live_details.get("scheduledStartTime"):
        return "Livestream", "replay"

    if duration_seconds <= 180:
        return "Short", "none"
    return "Long-form", "none"


def _video_sample(item: dict) -> dict:
    stats = item.get("statistics", {})
    content = item.get("contentDetails", {})
    snippet = item.get("snippet", {})
    duration_seconds = parse_youtube_duration(content.get("duration", ""))
    video_type, live_status = _video_classification(item, duration_seconds)

    published_raw = snippet.get("publishedAt")
    published_at = None
    if published_raw:
        published_at = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))

    thumbnails = snippet.get("thumbnails", {})
    thumbnail = (
        thumbnails.get("high", {}).get("url")
        or thumbnails.get("medium", {}).get("url")
        or thumbnails.get("default", {}).get("url")
    )

    video_id = item.get("id")
    return {
        "id": video_id,
        "channelId": snippet.get("channelId"),
        "channel": snippet.get("channelTitle", ""),
        "title": snippet.get("title", "Untitled"),
        "thumbnail": thumbnail,
        "youtubeUrl": (
            f"https://www.youtube.com/watch?v={video_id}" if video_id else None
        ),
        "views": _to_int(stats.get("viewCount")),
        "likes": _to_int(stats.get("likeCount")),
        "comments": _to_int(stats.get("commentCount")),
        "type": video_type,
        "liveStatus": live_status,
        "durationSeconds": duration_seconds,
        "publishedAt": published_at,
        "liveBroadcastContent": snippet.get("liveBroadcastContent", "none"),
    }


def _chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _to_int(value: str | int | None) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0

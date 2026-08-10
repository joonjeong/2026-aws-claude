"""YouTube trending collector built on labkit.poller.PollingCollector.

Two fetch modes, selected by environment:
- Live:    videos.list(chart=mostPopular, regionCode=KR, maxResults=30,
           part=snippet,statistics) via httpx. Requires YT_API_KEY.
- Fixture: YT_FIXTURE=<json path> loads pre-normalized snapshots from a
           file instead of calling the API (key-less verification mode).

Isolation rules (spec):
- Upstream error *bodies* go to the log only; exceptions and API responses
  carry the status code alone (no project/key leakage).
- One malformed item never kills a cycle (per-item try/except).
- A missing YT_API_KEY keeps the app healthy: every cycle records a
  failure in collector status and /api/trending serves empty data.

The fetch returns a list of (bucket, snapshot) pairs; on_result puts each
into the SnapshotRingBuffer-backed store (idempotent per bucket).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx

from labkit.cache import time_bucket
from labkit.poller import PollingCollector

from ....archive import archive_snapshot
from .. import config
from ..store.snapshots import SnapshotStore

logger = logging.getLogger(__name__)

# Category id -> localized name. Seeded with defaults; refreshed once at
# startup from videoCategories(hl=ko) when a key is available.
category_names: dict[str, str] = dict(config.DEFAULT_CATEGORY_NAMES)


async def load_category_names() -> None:
    """One-shot videoCategories(hl=ko) at startup. Failure is non-fatal:
    the defaults from config keep serving names."""
    api_key = os.environ.get(config.YT_API_KEY_ENV)
    if not api_key:
        logger.info("videoCategories skipped: %s not set, using default names",
                    config.YT_API_KEY_ENV)
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{config.YOUTUBE_API_BASE}/videoCategories",
                params={
                    "part": "snippet",
                    "regionCode": config.REGION_CODE,
                    "hl": "ko",
                    "key": api_key,
                },
            )
        if resp.status_code != 200:
            logger.error("videoCategories upstream %s: %s",
                         resp.status_code, resp.text[:2000])
            return
        for item in resp.json().get("items", []):
            cid = str(item.get("id", ""))
            title = (item.get("snippet") or {}).get("title")
            if cid and title:
                category_names[cid] = title
        logger.info("videoCategories loaded: %d names", len(category_names))
    except Exception as exc:  # startup best-effort only
        logger.warning("videoCategories failed (%s), using default names",
                       type(exc).__name__)


def _safe_int(value: Any) -> int:
    """statistics values arrive as string numbers; anything abnormal -> 0."""
    try:
        n = int(str(value))
        return n if n >= 0 else 0
    except (TypeError, ValueError):
        return 0


def _normalize_item(raw: dict[str, Any]) -> dict[str, Any]:
    snippet = raw.get("snippet") or {}
    stats = raw.get("statistics") or {}
    thumbs = snippet.get("thumbnails") or {}
    thumb = (thumbs.get("medium") or thumbs.get("high")
             or thumbs.get("default") or {})
    return {
        "video_id": str(raw["id"]),
        "title": str(snippet.get("title", "")),
        "channel": str(snippet.get("channelTitle", "")),
        "category_id": str(snippet.get("categoryId", "")),
        "thumbnail": str(thumb.get("url", "")),
        "view_count": _safe_int(stats.get("viewCount")),
        "like_count": _safe_int(stats.get("likeCount")),
        "published_at": str(snippet.get("publishedAt", "")),
    }


async def _fetch_live() -> list[tuple[int, dict[str, Any]]]:
    api_key = os.environ.get(config.YT_API_KEY_ENV)
    if not api_key:
        raise RuntimeError(f"{config.YT_API_KEY_ENV} is not set")
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{config.YOUTUBE_API_BASE}/videos",
            params={
                "part": "snippet,statistics",
                "chart": "mostPopular",
                "regionCode": config.REGION_CODE,
                "maxResults": config.MAX_RESULTS,
                "key": api_key,
            },
        )
    if resp.status_code != 200:
        # body to the log only; status code only in the exception
        logger.error("youtube upstream %s: %s", resp.status_code, resp.text[:2000])
        raise RuntimeError(f"youtube upstream status {resp.status_code}")

    items: list[dict[str, Any]] = []
    for raw in resp.json().get("items", []):
        try:
            items.append(_normalize_item(raw))
        except Exception as exc:  # one bad card never kills the cycle
            logger.warning("item skipped: %s", type(exc).__name__)
    snapshot = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "items": items,
    }
    return [(time_bucket(config.POLL_INTERVAL_S), snapshot)]


class FixtureLoader:
    """Loads consecutive snapshots from a JSON file (verification mode).

    Bucket assignment is frozen at first fetch: the last fixture snapshot
    takes the current bucket, earlier ones take the buckets just before it.
    Subsequent cycles re-put the same pairs and the ring buffer's per-bucket
    idempotency makes them no-ops.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self._buckets: list[int] | None = None

    async def fetch(self) -> list[tuple[int, dict[str, Any]]]:
        with open(self.path, encoding="utf-8") as fh:
            data = json.load(fh)
        snapshots = data["snapshots"] if isinstance(data, dict) else data
        if self._buckets is None:
            current = time_bucket(config.POLL_INTERVAL_S)
            n = len(snapshots)
            self._buckets = [current - (n - 1 - i) for i in range(n)]
        return list(zip(self._buckets, snapshots))


def create_collector(store: SnapshotStore) -> PollingCollector:
    fixture_path = os.environ.get(config.YT_FIXTURE_ENV)
    if fixture_path:
        logger.info("collector in fixture mode: %s", fixture_path)
        fetch = FixtureLoader(fixture_path).fetch
    else:
        fetch = _fetch_live

    def on_result(pairs: list[tuple[int, dict[str, Any]]]) -> None:
        for bucket, snapshot in pairs:
            if store.put(bucket, snapshot):
                # 신규 버킷만 이력 아카이브 (best-effort) — 재수집 no-op 유지
                archive_snapshot("trend", "trending", {"bucket": bucket, **snapshot})

    return PollingCollector(
        name="youtube-trending",
        interval_s=config.POLL_INTERVAL_S,
        fetch=fetch,
        on_result=on_result,
    )

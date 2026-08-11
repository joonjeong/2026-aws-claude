"""trend — YouTube 인기 동영상 (KR, mostPopular 30). 주기·정규화는 hub trend와 동일.

이식 원본: hub/backend/app/modules/trend/collector/youtube.py. import 금지.

- 키(YT_API_KEY)는 hub와 공유 — 합산 쿼터 ≈ 2,880유닛/일 (README 명시, 설계 §7.2)
- 키·응답 본문은 예외/meta에 절대 싣지 않는다 (hub 격리 규칙과 동일)
- 키 부재 시 build()가 None → 소스 비활성, 프로세스는 정상
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

from ..core.source import Record

log = logging.getLogger("datalake.trend")

API_BASE = "https://www.googleapis.com/youtube/v3"
KEY_ENV = "YT_API_KEY"
REGION_CODE = "KR"
MAX_RESULTS = 30
TIMEOUT_S = 15.0  # 권장 스케줄: 60s (hub POLL_INTERVAL_S)


def _safe_int(value: Any) -> int:
    """statistics 값은 문자열 숫자 — 비정상은 전부 0 (hub _safe_int와 동일)."""
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


def normalize(payload: dict) -> list[dict]:
    items: list[dict] = []
    for raw in payload.get("items") or []:
        try:
            items.append(_normalize_item(raw))
        except Exception as exc:  # 항목 단위 격리
            log.warning("item skipped: %s", type(exc).__name__)
    return items


class TrendClient:
    id = "trend"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def fetch(self) -> list[Record]:
        api_key = os.environ.get(KEY_ENV)
        if not api_key:
            raise RuntimeError(f"{KEY_ENV} is not set")
        started = time.monotonic()
        async with httpx.AsyncClient(
            timeout=TIMEOUT_S, transport=self._transport
        ) as client:
            resp = await client.get(
                f"{API_BASE}/videos",
                params={
                    "part": "snippet,statistics",
                    "chart": "mostPopular",
                    "regionCode": REGION_CODE,
                    "maxResults": MAX_RESULTS,
                    "key": api_key,
                },
            )
        if resp.status_code != 200:
            # 본문은 로그로만, 예외에는 상태코드만 (키/프로젝트 정보 비유출)
            log.error("youtube upstream %s: %s", resp.status_code, resp.text[:2000])
            raise RuntimeError(f"youtube upstream status {resp.status_code}")
        return [
            Record(
                source=self.id,
                kind="trending",
                payload=resp.json(),
                meta={
                    "region": REGION_CODE,
                    "status": resp.status_code,
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                },
            )
        ]

def build() -> TrendClient | None:
    if not os.environ.get(KEY_ENV):
        log.info("trend 비활성: %s 미설정", KEY_ENV)
        return None
    return TrendClient()

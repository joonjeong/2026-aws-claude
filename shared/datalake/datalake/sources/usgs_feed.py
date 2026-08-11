"""usgs_feed — USGS 지진 피드 상류. 생산 kind: quake.

이식 원본: hub/backend/app/modules/quake/collector.py (코드 이식, import 금지).
Record.payload는 USGS 응답 전체(FeatureCollection) 원본.
권장 스케줄: 60s (hub QUAKE_POLL_INTERVAL_S와 동일 — README 참조).
"""

from __future__ import annotations

import logging
import time

import httpx

from ..core.env import env_float, env_str
from ..core.source import Record

log = logging.getLogger("datalake.usgs_feed")

FEED_URL = env_str(
    "DATALAKE_USGS_FEED_URL",
    "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson",
)
TIMEOUT_S = env_float("DATALAKE_USGS_FEED_TIMEOUT_S", 10.0)


def _float(value, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if result == result else default  # NaN -> default


def _time_ms(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def normalize(payload: dict) -> list[dict]:
    """hub quake normalize()와 동일 — feature 단위 격리, NaN 방어."""
    events: list[dict] = []
    for feature in payload.get("features") or []:
        try:
            event_id = feature.get("id")
            if not event_id:
                continue
            props = feature.get("properties") or {}
            coords = ((feature.get("geometry") or {}).get("coordinates") or [])
            coords = list(coords) + [0, 0, 0]  # 짧은 좌표 배열 패딩
            place = props.get("place")
            events.append(
                {
                    "id": str(event_id),
                    "mag": _float(props.get("mag")),
                    "place": str(place) if place else "unknown",
                    "time": _time_ms(props.get("time")),
                    "lon": _float(coords[0]),
                    "lat": _float(coords[1]),
                    "depth_km": _float(coords[2]),
                }
            )
        except Exception:  # 깨진 feature 하나가 나머지를 못 죽이게
            log.warning("skipping malformed feature", exc_info=True)
    return events


class UsgsFeedClient:
    id = "usgs_feed"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def fetch(self) -> list[Record]:
        started = time.monotonic()
        async with httpx.AsyncClient(
            timeout=TIMEOUT_S, transport=self._transport
        ) as client:
            resp = await client.get(FEED_URL)
            resp.raise_for_status()
            payload = resp.json()
        return [
            Record(
                source=self.id,
                kind="quake",
                payload=payload,
                meta={
                    "url": FEED_URL,
                    "status": resp.status_code,
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                },
            )
        ]


def build() -> UsgsFeedClient:
    return UsgsFeedClient()

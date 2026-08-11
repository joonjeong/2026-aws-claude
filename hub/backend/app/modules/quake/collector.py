"""USGS feed collector: 60s labkit PollingCollector + per-feature normalization.

A failed cycle is isolated by PollingCollector (logged, retried next cycle);
a malformed feature is isolated by the per-item try/except in normalize().
"""
from __future__ import annotations

import logging

import httpx
from labkit import PollingCollector

from ...archive import archive_insert
from . import config, schema
from .store import store

logger = logging.getLogger(__name__)


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


def normalize(features: list) -> list[dict]:
    events: list[dict] = []
    for feature in features:
        try:
            event_id = feature.get("id")
            if not event_id:
                continue
            props = feature.get("properties") or {}
            coords = ((feature.get("geometry") or {}).get("coordinates") or [])
            coords = list(coords) + [0, 0, 0]  # pad short coordinate arrays
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
        except Exception:  # one bad feature never kills the rest
            logger.warning("skipping malformed feature", exc_info=True)
    return events


async def fetch_feed() -> list[dict]:
    async with httpx.AsyncClient(timeout=config.FETCH_TIMEOUT_S) as client:
        resp = await client.get(config.USGS_FEED_URL)
        resp.raise_for_status()
        data = resp.json()
    return normalize(data.get("features") or [])


def _on_result(events: list[dict]) -> None:
    store.ingest(events)
    # 정규화 아카이브 (best-effort) — id PK의 INSERT OR IGNORE가 재관측을 걸러낸다
    archive_insert(schema.INSERT_EVENT, [
        (e["id"], e["mag"], e["place"], e["time"], e["lon"], e["lat"], e["depth_km"])
        for e in events
    ])


collector = PollingCollector(
    name="quake-usgs",
    interval_s=config.POLL_INTERVAL_S,
    fetch=fetch_feed,
    on_result=_on_result,
)

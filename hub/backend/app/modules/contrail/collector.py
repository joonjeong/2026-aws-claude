"""OpenSky 폴러 2개: 전 세계 스냅샷 + 관심지역 고해상도 (trail·아카이브는 지역만)."""
from __future__ import annotations

import time

import httpx
from labkit import PollingCollector

from ...archive import archive_insert
from . import config, schema
from .auth import get_token
from .normalize import normalize_states
from .store import store


async def _fetch(params: dict | None = None) -> list[dict]:
    token = await get_token()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx.AsyncClient(timeout=config.FETCH_TIMEOUT_S) as client:
        resp = await client.get(config.OPENSKY_URL, params=params, headers=headers)
        resp.raise_for_status()
        payload = resp.json()
    return normalize_states(payload, time.time())


async def fetch_global() -> list[dict]:
    return await _fetch()


async def fetch_region() -> list[dict]:
    lat_min, lon_min, lat_max, lon_max = store.preset()["bbox"]
    return await _fetch({
        "lamin": lat_min, "lomin": lon_min, "lamax": lat_max, "lomax": lon_max,
    })


def _on_global(flights: list[dict]) -> None:
    store.set_global(flights)


def _on_region(flights: list[dict]) -> None:
    dims: list[tuple] = []
    facts: list[tuple] = []
    for f in flights:
        added = store.trails.ingest(f)
        if added:
            dims.append((
                f["id"], f["callsign"], f["origin_country"], f["ts"], f["ts"],
            ))
            if store.should_archive(f["id"], f["ts"]):
                facts.append((
                    f["id"], f["ts"], f["lon"], f["lat"], f["alt_m"],
                    f["velocity_ms"], f["track_deg"], int(f["on_ground"]),
                ))
    # 사이클당 배치 기록 (best-effort — 실패는 로그만)
    archive_insert(schema.UPSERT_AIRCRAFT, dims)
    archive_insert(schema.INSERT_POSITION, facts)
    store.trails.prune()


global_collector = PollingCollector(
    name="contrail-global",
    interval_s=config.GLOBAL_INTERVAL_S,
    fetch=fetch_global,
    on_result=_on_global,
)

region_collector = PollingCollector(
    name="contrail-region",
    interval_s=config.REGION_INTERVAL_S,
    fetch=fetch_region,
    on_result=_on_region,
)

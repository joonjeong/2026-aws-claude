"""폴러 2개: 전 세계 스냅샷 + 관심지역 고해상도 (trail·아카이브는 지역만).

소스는 config.SOURCE로 선택 — adsblol(re-api, bbox 직접 조회) | opensky(레거시).
"""
from __future__ import annotations

import time

import httpx
from labkit import PollingCollector

from ...archive import archive_insert
from . import config, schema
from .auth import get_token
from .normalize import normalize_readsb, normalize_states
from .store import store

GLOBAL_BBOX = (-90.0, -180.0, 90.0, 180.0)


def box_param(bbox: tuple) -> str:
    """내부 bbox(lat_min, lon_min, lat_max, lon_max) → re-api box 파라미터.

    re-api는 lat_min,lat_max,lon_min,lon_max 순서 — OpenSky(lamin,lomin,
    lamax,lomax)와 달라 헷갈리기 쉬운 지점이라 헬퍼로 고정.
    """
    lat_min, lon_min, lat_max, lon_max = bbox
    return f"{lat_min},{lat_max},{lon_min},{lon_max}"


async def _fetch_opensky(params: dict | None = None) -> list[dict]:
    token = await get_token()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx.AsyncClient(timeout=config.FETCH_TIMEOUT_S) as client:
        resp = await client.get(config.OPENSKY_URL, params=params, headers=headers)
        resp.raise_for_status()
        payload = resp.json()
    return normalize_states(payload, time.time())


def adsblol_url(base: str, bbox: tuple) -> str:
    """re-api 요청 URL — 원시 쿼리로 조립.

    re-api는 %2C(콤마 인코딩)도 jv2=(등호 포함)도 400으로 거부하므로
    httpx의 params 인코딩을 쓰지 않는다. jv2는 v2 JSON(ac 배열) 응답 플래그.
    """
    return f"{base}?box={box_param(bbox)}&jv2"


async def _fetch_adsblol(bbox: tuple) -> list[dict]:
    async with httpx.AsyncClient(timeout=config.FETCH_TIMEOUT_S) as client:
        resp = await client.get(adsblol_url(config.ADSBLOL_URL, bbox))
        resp.raise_for_status()
        payload = resp.json()
    return normalize_readsb(payload, time.time())


async def fetch_global() -> list[dict]:
    if config.SOURCE == "opensky":
        return await _fetch_opensky()
    return await _fetch_adsblol(GLOBAL_BBOX)


async def fetch_region() -> list[dict]:
    bbox = store.preset()["bbox"]
    if config.SOURCE == "opensky":
        lat_min, lon_min, lat_max, lon_max = bbox
        return await _fetch_opensky({
            "lamin": lat_min, "lomin": lon_min, "lamax": lat_max, "lomax": lon_max,
        })
    return await _fetch_adsblol(bbox)


def _on_global(flights: list[dict]) -> None:
    store.set_global(flights)


def _in_bbox(lat: float, lon: float, bbox: tuple) -> bool:
    lat_min, lon_min, lat_max, lon_max = bbox
    return lat_min <= lat <= lat_max and lon_min <= lon <= lon_max


def _on_region(flights: list[dict]) -> None:
    bbox = store.preset()["bbox"]
    dims: list[tuple] = []
    facts: list[tuple] = []
    for f in flights:
        if not _in_bbox(f["lat"], f["lon"], bbox):
            continue  # 프리셋 전환 경합: 이전 bbox로 요청된 응답이 리셋 이후 도착
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

"""폴러 2개: 전 세계 스냅샷(뷰용) + 전 프리셋 지역 상시 수집(trail·아카이브).

소스는 config.SOURCE로 선택 — adsblol(re-api, bbox 직접 조회) | opensky(레거시).
지역 폴러는 매 사이클 모든 프리셋 bbox를 병렬 조회해 병합한다 — 프리셋 전환은
서버 상태를 바꾸지 않고 조회 대상만 바뀐다 (상시 수집 구조, 2026-08-11).
"""
from __future__ import annotations

import asyncio
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


async def _fetch_bbox(bbox: tuple) -> list[dict]:
    if config.SOURCE == "opensky":
        lat_min, lon_min, lat_max, lon_max = bbox
        return await _fetch_opensky({
            "lamin": lat_min, "lomin": lon_min, "lamax": lat_max, "lomax": lon_max,
        })
    return await _fetch_adsblol(bbox)


async def fetch_global() -> list[dict]:
    if config.SOURCE == "opensky":
        return await _fetch_opensky()
    return await _fetch_adsblol(GLOBAL_BBOX)


def merge_flights(batches: list[list[dict]]) -> list[dict]:
    """프리셋별 응답 병합 — 겹침 구간(kr·japan 등) 중복 개체는 1건으로."""
    merged: dict[str, dict] = {}
    for batch in batches:
        for f in batch:
            merged[f["id"]] = f
    return list(merged.values())


async def fetch_regions() -> list[dict]:
    """모든 프리셋 bbox를 순차 조회해 병합.

    re-api는 IP당 요청 빈도를 제한한다(병렬 4요청 → 420 Enhance Your Calm,
    2026-08-11 실측). 요청 사이 1.1초 간격 — 기동 직후 전지구 폴러와의 동시
    출발도 첫 sleep으로 비껴간다. 부분 실패는 사이클 실패로 전파
    (PollingCollector가 실패 카운트·재시도 담당).
    """
    batches: list[list[dict]] = []
    for p in config.PRESETS:
        await asyncio.sleep(1.1)
        batches.append(await _fetch_bbox(p["bbox"]))
    return merge_flights(batches)


def _on_global(flights: list[dict]) -> None:
    store.set_global(flights)


def _on_regions(flights: list[dict]) -> None:
    dims, facts = store.ingest_regions(flights)
    # 사이클당 배치 기록 (best-effort — 실패는 로그만)
    archive_insert(schema.UPSERT_AIRCRAFT, dims)
    archive_insert(schema.INSERT_POSITION, facts)


global_collector = PollingCollector(
    name="contrail-global",
    interval_s=config.GLOBAL_INTERVAL_S,
    fetch=fetch_global,
    on_result=_on_global,
)

region_collector = PollingCollector(
    name="contrail-regions",
    interval_s=config.REGION_INTERVAL_S,
    fetch=fetch_regions,
    on_result=_on_regions,
)

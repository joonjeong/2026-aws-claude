"""Contrail API routes — paths relative to the hub's /api/contrail prefix.

프리셋은 서버 상태가 아니라 조회 파라미터다(상시 수집 구조): 모든 프리셋이
항상 수집·아카이브되고 있으므로 전환에 쿨다운·킥·리셋이 필요 없다.
"""
from __future__ import annotations

import time
from collections import Counter

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from labkit import BedrockError

from ...archive import archive_query
from . import config, llm
from .collector import global_collector, region_collector
from .store import store

router = APIRouter()


def health() -> dict:
    failing = (global_collector.consecutive_failures
               + region_collector.consecutive_failures)
    return {
        "status": "ok" if failing == 0 else "degraded",
        "source": config.SOURCE,
        "auth": "oauth" if config.HAS_AUTH else "anonymous",
        "global_flights": len(store.global_flights),
        "region_flights": {pid: len(ts) for pid, ts in store.stores.items()},
        "collectors": [global_collector.status, region_collector.status],
    }


@router.get("/healthz")
async def healthz():
    return health()


def _global_stats(flights: list[dict]) -> dict:
    airborne = [f for f in flights if not f.get("on_ground")]
    # 기종 미상(None)은 집계에서 제외 — opensky 롤백 경로에선 전부 미상이라 None
    types = Counter(t for f in flights if (t := f.get("type")))
    return {
        "count": len(flights),
        "airborne": len(airborne),
        "top_type": types.most_common(1)[0][0] if types else None,
        "last_fetch": store.global_fetch,
    }


def _region_stats(flights: list[dict], last_ingest: float | None) -> dict:
    return {
        "count": len(flights),
        "airborne": len([f for f in flights if not f.get("on_ground")]),
        "last_ingest": last_ingest,
    }


def _resolve_preset(preset: str | None) -> str:
    pid = preset or config.DEFAULT_PRESET
    if pid not in store.stores:
        raise HTTPException(status_code=422, detail=f"unknown preset: {pid}")
    return pid


@router.get("/global")
async def global_view():
    return {
        "flights": store.global_flights,
        "stats": _global_stats(store.global_flights),
    }


@router.get("/region")
async def region(preset: str | None = None):
    pid = _resolve_preset(preset)
    trail_store = store.region(pid)
    trail_store.prune()
    flights = trail_store.entities()
    return {
        "flights": flights,
        "trails": trail_store.trails(),
        "preset": pid,
        "stats": _region_stats(flights, trail_store.last_ingest),
    }


@router.get("/preset")
async def get_preset():
    return {"presets": config.PRESETS, "default": config.DEFAULT_PRESET}


@router.get("/history")
async def history(id: str, hours: float = Query(24, gt=0, le=168)):
    cutoff = time.time() - hours * 3600
    rows = archive_query(
        "SELECT ts, lon, lat FROM contrail_positions"
        " WHERE icao24 = ? AND ts >= ? ORDER BY ts",
        (id, cutoff),
    )
    return {"id": id, "points": [[r[0], r[1], r[2]] for r in rows]}


@router.post("/brief")
async def brief(preset: str | None = None):
    pid = _resolve_preset(preset)
    trail_store = store.region(pid)
    trail_store.prune()
    region_flights = trail_store.entities()
    notable = sorted(
        region_flights, key=lambda f: f.get("velocity_ms") or 0, reverse=True
    )[:10]
    try:
        text, cached, bucket = await llm.generate_brief(
            _global_stats(store.global_flights),
            _region_stats(region_flights, trail_store.last_ingest),
            store.preset(pid)["label"],
            notable,
        )
    except BedrockError as exc:
        if exc.status_code == 503:
            return JSONResponse(status_code=503, content={
                "error": "LLM 토큰이 설정되지 않았습니다",
                "detail": "환경변수 AWS_BEARER_TOKEN_BEDROCK을 설정하면 브리핑을 사용할 수 있습니다.",
            })
        return JSONResponse(status_code=502, content={"error": exc.message})
    return {"brief": text, "cached": cached, "bucket": bucket}

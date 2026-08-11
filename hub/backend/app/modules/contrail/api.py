"""Contrail API routes — paths relative to the hub's /api/contrail prefix."""
from __future__ import annotations

import asyncio
import time
from collections import Counter

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from labkit import BedrockError
from pydantic import BaseModel

from ...archive import archive_query
from . import config, llm
from .collector import global_collector, region_collector
from .store import store

router = APIRouter()

_kick_task: asyncio.Task | None = None


def health() -> dict:
    failing = (global_collector.consecutive_failures
               + region_collector.consecutive_failures)
    return {
        "status": "ok" if failing == 0 else "degraded",
        "source": config.SOURCE,
        "auth": "oauth" if config.HAS_AUTH else "anonymous",
        "global_flights": len(store.global_flights),
        "region_flights": len(store.trails),
        "preset": store.active_preset,
        "collectors": [global_collector.status, region_collector.status],
    }


@router.get("/healthz")
async def healthz():
    return health()


def _global_stats(flights: list[dict]) -> dict:
    airborne = [f for f in flights if not f.get("on_ground")]
    countries = Counter(f.get("origin_country") or "?" for f in flights)
    return {
        "count": len(flights),
        "airborne": len(airborne),
        "top_country": countries.most_common(1)[0][0] if countries else None,
        "last_fetch": store.global_fetch,
    }


def _region_stats(flights: list[dict]) -> dict:
    return {
        "count": len(flights),
        "airborne": len([f for f in flights if not f.get("on_ground")]),
        "last_ingest": store.trails.last_ingest,
    }


@router.get("/global")
async def global_view():
    return {
        "flights": store.global_flights,
        "stats": _global_stats(store.global_flights),
    }


@router.get("/region")
async def region():
    store.trails.prune()
    flights = store.trails.entities()
    return {
        "flights": flights,
        "trails": store.trails.trails(),
        "preset": store.active_preset,
        "stats": _region_stats(flights),
    }


class PresetBody(BaseModel):
    id: str


@router.get("/preset")
async def get_preset():
    return {"presets": config.PRESETS, "active": store.active_preset}


@router.post("/preset")
async def set_preset(body: PresetBody):
    if body.id not in {p["id"] for p in config.PRESETS}:
        raise HTTPException(status_code=422, detail=f"unknown preset: {body.id}")
    if body.id != store.active_preset:
        now = time.time()
        if (
            store.last_preset_switch is not None
            and now - store.last_preset_switch < config.PRESET_COOLDOWN_S
        ):
            raise HTTPException(status_code=429, detail="preset switch cooldown")
        store.last_preset_switch = now
        store.active_preset = body.id
        store.reset()
        # 다음 정규 주기를 기다리지 않고 새 bbox로 즉시 1회 수집
        global _kick_task
        _kick_task = asyncio.create_task(region_collector.run_once())
    return {"presets": config.PRESETS, "active": store.active_preset}


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
async def brief():
    store.trails.prune()
    region_flights = store.trails.entities()
    notable = sorted(
        region_flights, key=lambda f: f.get("velocity_ms") or 0, reverse=True
    )[:10]
    try:
        text, cached, bucket = await llm.generate_brief(
            _global_stats(store.global_flights),
            _region_stats(region_flights),
            store.preset()["label"],
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

"""Wake API routes — paths relative to the hub's /api/wake prefix."""
from __future__ import annotations

import time
from collections import Counter

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from labkit import BedrockError
from pydantic import BaseModel

from ...archive import archive_query
from . import config, llm
from .collector import collector
from .store import store

router = APIRouter()


def health() -> dict:
    st = collector.status
    if not config.AIS_KEY:
        status = "no_key"
    elif st["connected"]:
        status = "ok"
    else:
        status = "degraded"
    return {
        "status": status,
        "vessels": len(store.trails),
        "preset": store.active_preset,
        "collector": st,
    }


@router.get("/healthz")
async def healthz():
    return health()


def _stats(vessels: list[dict]) -> dict:
    moving = [v for v in vessels if (v.get("sog_kn") or 0) >= 0.5]
    types = Counter((v.get("ship_type") or "기타") for v in vessels)
    return {
        "count": len(vessels),
        "moving": len(moving),
        "top_type": types.most_common(1)[0][0] if types else None,
        "max_sog": max((v.get("sog_kn") or 0 for v in vessels), default=0),
        "last_ingest": store.trails.last_ingest,
    }


@router.get("/region")
async def region():
    store.trails.prune()
    vessels = store.trails.entities()
    return {
        "vessels": vessels,
        "trails": store.trails.trails(),
        "preset": store.active_preset,
        "stats": _stats(vessels),
        "status": "no_key" if not config.AIS_KEY else "ok",
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
        store.reset()          # 다른 해역의 trail이 섞이지 않게
        collector.resubscribe()  # 라이브 소켓에 새 bbox 구독 재전송
    return {"presets": config.PRESETS, "active": store.active_preset}


@router.get("/history")
async def history(id: str, hours: float = Query(24, gt=0, le=168)):
    cutoff = time.time() - hours * 3600
    rows = archive_query(
        "SELECT ts, lon, lat FROM wake_positions"
        " WHERE mmsi = ? AND ts >= ? ORDER BY ts",
        (id, cutoff),
    )
    return {"id": id, "points": [[r[0], r[1], r[2]] for r in rows]}


@router.post("/brief")
async def brief():
    vessels = store.trails.entities()
    stats = _stats(vessels)
    notable = sorted(vessels, key=lambda v: v.get("sog_kn") or 0, reverse=True)[:10]
    try:
        text, cached, bucket = await llm.generate_brief(
            stats, store.preset()["label"], notable
        )
    except BedrockError as exc:
        if exc.status_code == 503:
            return JSONResponse(status_code=503, content={
                "error": "LLM 토큰이 설정되지 않았습니다",
                "detail": "환경변수 AWS_BEARER_TOKEN_BEDROCK을 설정하면 브리핑을 사용할 수 있습니다.",
            })
        return JSONResponse(status_code=502, content={"error": exc.message})
    return {"brief": text, "cached": cached, "bucket": bucket}

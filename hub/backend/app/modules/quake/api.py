"""Quake API routes — paths relative to the hub's /api/quake prefix."""
from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from labkit import BedrockError

from . import llm
from .collector import collector
from .store import store

router = APIRouter()


def health() -> dict:
    status = "ok" if collector.consecutive_failures == 0 else "degraded"
    return {"status": status, "events": len(store), "collector": collector.status}


@router.get("/healthz")
async def healthz():
    return health()


@router.get("/quakes")
async def quakes(
    hours: float = Query(24, gt=0, le=48),
    min_mag: float = Query(2.5, ge=0, le=10),
):
    events = store.query(hours=hours, min_mag=min_mag)
    return {"events": events, "stats": store.stats(events)}


@router.post("/brief")
async def brief():
    events_24h = store.query(hours=24, min_mag=0)
    stats = store.stats(events_24h)
    top10 = sorted(events_24h, key=lambda e: e["mag"], reverse=True)[:10]
    try:
        text, cached, bucket = await llm.generate_brief(stats, top10)
    except BedrockError as exc:
        if exc.status_code == 503:
            return JSONResponse(
                status_code=503,
                content={
                    "error": "LLM 토큰이 설정되지 않았습니다",
                    "detail": "환경변수 AWS_BEARER_TOKEN_BEDROCK을 설정하면 브리핑을 사용할 수 있습니다.",
                },
            )
        # upstream failure: status code only, body already logged by labkit
        return JSONResponse(status_code=502, content={"error": exc.message})
    return {"brief": text, "cached": cached, "bucket": bucket}

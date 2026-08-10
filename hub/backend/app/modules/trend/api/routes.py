"""API routes — the contract from the design doc §5, hub-namespaced.

Paths are relative; the hub mounts this router under /api/trend, so
/trending -> /api/trend/trending, /trends -> /api/trend/trends,
/brief -> /api/trend/brief, /healthz -> /api/trend/healthz.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from labkit.bedrock import BedrockError

from .. import config, state
from ..collector import youtube as collector_mod
from ..derive.trends import derive_items, derive_stats, derive_timeseries
from ..llm import brief as brief_mod

router = APIRouter()


def _collector_status() -> dict[str, Any]:
    if state.collector is None:
        return {"name": "youtube-trending", "last_success": None,
                "last_error": "not started", "cycles": 0,
                "consecutive_failures": 0}
    return state.collector.status


@router.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {"status": "ok", "snapshots": len(state.store)}


@router.get("/trending")
async def trending(category: str | None = None) -> dict[str, Any]:
    latest = state.store.latest()
    if latest is None:  # degraded: healthy app, empty data + source status
        return {
            "captured_at": None,
            "items": [],
            "stats": {"total_views": 0, "channel_count": 0,
                      "top_category": None, "exited": 0},
            "collector": _collector_status(),
        }
    _, snapshot = latest
    previous = state.store.previous()
    items, exited = derive_items(
        snapshot.get("items", []),
        previous[1].get("items", []) if previous else None,
        collector_mod.category_names,
    )
    stats = derive_stats(items, exited)  # stats over the full 30, pre-filter
    if category is not None:
        items = [it for it in items if it["category_id"] == category]
    return {
        "captured_at": snapshot.get("captured_at"),
        "items": items,
        "stats": stats,
        "collector": _collector_status(),
    }


@router.get("/trends")
async def trends(hours: float = 1) -> dict[str, Any]:
    if hours <= 0:
        raise HTTPException(status_code=400, detail="hours must be positive")
    n = max(1, int(hours * 3600 // config.POLL_INTERVAL_S))
    # window(n+1): the extra leading snapshot gives the first returned
    # point a real entered/exited baseline when history allows.
    pairs = state.store.window(n + 1)
    points = derive_timeseries(
        pairs, config.POLL_INTERVAL_S, collector_mod.category_names
    )
    return {"points": points[-n:]}


@router.post("/brief")
async def brief(mode: str = "now") -> Any:
    if mode not in ("now", "daily"):
        raise HTTPException(status_code=400, detail="mode must be now or daily")
    latest = state.store.latest()
    if latest is None:
        return JSONResponse(
            status_code=503,
            content={"error": "no_snapshot",
                     "message": "아직 수집된 스냅샷이 없어 브리핑을 만들 수 없습니다."},
        )
    previous = state.store.previous()
    try:
        text, cached, bucket = await brief_mod.generate(
            mode, latest[1], previous[1] if previous else None,
            collector_mod.category_names,
        )
    except BedrockError as exc:
        if exc.status_code == 503:
            message = ("브리핑 LLM 키(AWS_BEARER_TOKEN_BEDROCK)가 설정되지 않아 "
                       "브리핑 기능이 비활성화되어 있습니다.")
        else:
            message = f"브리핑 생성 중 오류가 발생했습니다 ({exc.message})."
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": "brief_unavailable", "message": message},
        )
    return {"brief": text, "cached": cached, "bucket": bucket}

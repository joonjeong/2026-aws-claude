"""Flashpoint API routes — paths relative to the hub's /api/flashpoint prefix.

인메모리 스토어 없음: 15분 갱신 데이터라 SQLite를 직접 조회한다 (설계 §3).
프리셋은 조회 파라미터 — 서버 상태를 바꾸지 않는다.
"""
from __future__ import annotations

import time
from collections import Counter

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from labkit import BedrockError

from ...archive import archive_query
from . import config, llm
from .collector import collector, ingest_stats

router = APIRouter()

_COLS = ("event_id", "ts", "event_day", "code", "root", "quad", "goldstein",
         "mentions", "articles", "tone", "actor1", "actor2", "lat", "lon",
         "country", "source_url")


def health() -> dict:
    return {
        "status": "ok" if collector.consecutive_failures == 0 else "degraded",
        "last_batch": ingest_stats["last_batch"],
        "total_rows": ingest_stats["total_rows"],
        "collector": collector.status,
    }


@router.get("/healthz")
async def healthz():
    return health()


def events_query(cutoff: float, bbox: tuple | None,
                 limit: int | None = None) -> tuple[str, tuple]:
    """이벤트 조회 SQL 조립 — bbox 없으면 전 세계."""
    sql = f"SELECT {', '.join(_COLS)} FROM flashpoint_events WHERE ts >= ?"
    params: list = [cutoff]
    if bbox is not None:
        lat_min, lon_min, lat_max, lon_max = bbox
        sql += " AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?"
        params += [lat_min, lat_max, lon_min, lon_max]
    sql += f" ORDER BY ts DESC LIMIT {limit or config.EVENTS_LIMIT}"
    return sql, tuple(params)


def _resolve_preset(preset: str | None) -> dict | None:
    """None → 전 세계(bbox 없음), 그 외 프리셋 dict. 미지의 id는 422."""
    if preset is None:
        return None
    p = next((p for p in config.PRESETS if p["id"] == preset), None)
    if p is None:
        raise HTTPException(status_code=422, detail=f"unknown preset: {preset}")
    return p


def _stats(events: list[dict]) -> dict:
    countries = Counter(e["country"] for e in events if e.get("country"))
    return {
        "count": len(events),
        "by_root": dict(Counter(e["root"] for e in events if e.get("root"))),
        "top_country": countries.most_common(1)[0][0] if countries else None,
        "last_fetch": collector.status.get("last_success"),
    }


def _fetch_events(hours: float, bbox: tuple | None) -> list[dict]:
    sql, params = events_query(time.time() - hours * 3600, bbox)
    return [dict(zip(_COLS, r)) for r in archive_query(sql, params)]


@router.get("/events")
async def events(preset: str | None = None,
                 hours: float = Query(24, gt=0, le=168)):
    p = _resolve_preset(preset)
    rows = _fetch_events(hours, p["bbox"] if p else None)
    return {
        "events": rows,
        "preset": p["id"] if p else None,
        "stats": _stats(rows),
    }


@router.get("/preset")
async def get_preset():
    return {"presets": config.PRESETS, "default": config.DEFAULT_PRESET}


@router.post("/brief")
async def brief(preset: str | None = None):
    p = _resolve_preset(preset)
    rows = _fetch_events(24, p["bbox"] if p else None)
    label = p["label"] if p else "전 세계"
    notable = sorted(rows, key=lambda e: e.get("mentions") or 0, reverse=True)[:10]
    try:
        text, cached, bucket = await llm.generate_brief(_stats(rows), label, notable)
    except BedrockError as exc:
        if exc.status_code == 503:
            return JSONResponse(status_code=503, content={
                "error": "LLM 토큰이 설정되지 않았습니다",
                "detail": "환경변수 AWS_BEARER_TOKEN_BEDROCK을 설정하면 브리핑을 사용할 수 있습니다.",
            })
        return JSONResponse(status_code=502, content={"error": exc.message})
    return {"brief": text, "cached": cached, "bucket": bucket}

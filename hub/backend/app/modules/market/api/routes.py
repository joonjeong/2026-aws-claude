"""API routes (hub module: paths are RELATIVE — hub mounts them under
/api/market). All quote/overview/chart/detail data goes through one
labkit.cache.TTLCache (single-flight). Cache keys per design doc:
quotes:us / quotes:kr / overview / chart:{symbol}:{range} / detail:{symbol}
/ orderbook:{symbol} / investors:{symbol} / news:{symbol}.

Responses carry an X-Cache: HIT|MISS header (verification aid)."""
from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse
from labkit.cache import TTLCache
from pydantic import BaseModel

from ..core import config, hours
from ..services import ai, charts, kr, sim, us
from ..services import news as news_svc

log = logging.getLogger("market.api")
router = APIRouter()
cache = TTLCache()
_last_fetch: dict[str, float] = {}  # cache key -> unix time of last upstream fetch

# 심볼 화이트리스트: 임의 문자열이 캐시 키·상류 조회로 흘러가는 것을 차단
_KNOWN_SYMBOLS = {s for s, _ in config.US_SYMBOLS} | {s for s, _ in config.KR_SYMBOLS}


def _require_known(symbol: str) -> None:
    if symbol not in _KNOWN_SYMBOLS:
        raise HTTPException(status_code=404, detail=f"unknown symbol {symbol}")


async def _cached(key: str, ttl_s: float,
                  fetch: Callable[[], Awaitable[Any]]) -> tuple[Any, bool]:
    """get_or_fetch + hit flag (True when upstream fetch was NOT invoked)."""
    fetched = False

    async def wrapped() -> Any:
        nonlocal fetched
        fetched = True
        _last_fetch[key] = time.time()
        return await fetch()

    value = await cache.get_or_fetch(key, ttl_s, wrapped)
    return value, not fetched


def health_info() -> dict[str, Any]:
    """Module health: no pollers — report cache keys and last upstream fetches."""
    now = time.time()
    return {
        "status": "ok",
        "ai_token": ai.token_present(),
        "cached_keys": sorted(
            k for k, (exp, _) in cache._data.items() if exp > now  # noqa: SLF001
        ),
        "last_fetch": {
            k: round(now - t, 1) for k, t in sorted(_last_fetch.items())
        },  # seconds ago
    }


def _mark(response: Response, hit: bool) -> None:
    response.headers["X-Cache"] = "HIT" if hit else "MISS"


@router.get("/healthz")
async def healthz() -> dict[str, Any]:
    return health_info()


@router.get("/overview")
async def market_overview(response: Response) -> dict[str, Any]:
    errors: dict[str, str | None] = {"overview": None}

    async def fetch() -> dict[str, Any]:
        return await us.fetch_overview()

    try:
        data, hit = await _cached("overview", hours.overview_ttl(), fetch)
    except Exception as exc:  # noqa: BLE001 — degrade, don't 500
        log.error("overview fetch failed: %r", exc)
        data, hit = {"indices": [], "indicators": []}, False
        errors["overview"] = type(exc).__name__
    _mark(response, hit)
    return {**data, "errors": errors}


@router.get("/quotes")
async def market_quotes(response: Response) -> dict[str, Any]:
    errors: dict[str, str | None] = {"us": None, "kr": None}
    out: dict[str, Any] = {"us": [], "kr": []}
    hits: list[bool] = []
    for market, key, fetch in (
        ("us", "quotes:us", us.fetch_us_quotes),
        ("kr", "quotes:kr", kr.fetch_kr_quotes),
    ):
        try:
            rows, hit = await _cached(key, hours.quote_ttl(market.upper()), fetch)
            out[market] = rows
            hits.append(hit)
        except Exception as exc:  # noqa: BLE001 — per-source isolation
            log.error("quotes[%s] fetch failed: %r", market, exc)
            errors[market] = type(exc).__name__
            hits.append(False)
    _mark(response, all(hits) and bool(hits))
    return {**out, "errors": errors}


async def _detail_cached(symbol: str) -> tuple[dict[str, Any], bool]:
    """Cached detail fetch shared by detail/AI/orderbook/investors routes.
    Maps LookupError -> 404, other upstream failures -> 502 (status only)."""
    market = "KR" if kr.is_kr_symbol(symbol) else "US"
    try:
        return await _cached(f"detail:{symbol}", hours.quote_ttl(market),
                             lambda: charts.fetch_detail(symbol))
    except LookupError:
        raise HTTPException(status_code=404, detail=f"unknown symbol {symbol}")
    except Exception as exc:  # noqa: BLE001
        log.error("detail[%s] fetch failed: %r", symbol, exc)
        raise HTTPException(status_code=502, detail="upstream data source failed")


@router.get("/stocks/{symbol}")
async def stock_detail(symbol: str, response: Response) -> dict[str, Any]:
    _require_known(symbol)
    data, hit = await _detail_cached(symbol)
    _mark(response, hit)
    return data


@router.get("/stocks/{symbol}/chart")
async def stock_chart(symbol: str, response: Response, range: str = "1m") -> dict[str, Any]:
    _require_known(symbol)
    if range not in charts.RANGES:
        raise HTTPException(status_code=422,
                            detail=f"range must be one of {list(charts.RANGES)}")
    try:
        data, hit = await _cached(f"chart:{symbol}:{range}", config.CHART_TTL[range],
                                  lambda: charts.fetch_chart(symbol, range))
    except Exception as exc:  # noqa: BLE001
        log.error("chart[%s:%s] fetch failed: %r", symbol, range, exc)
        raise HTTPException(status_code=502, detail="upstream data source failed")
    if not data["candles"]:
        raise HTTPException(status_code=404, detail=f"no chart data for {symbol}")
    _mark(response, hit)
    return data


@router.get("/stocks/{symbol}/orderbook")
async def stock_orderbook(symbol: str, response: Response) -> dict[str, Any]:
    """SIMULATED order book — deterministic per price (see services/sim.py)."""
    _require_known(symbol)
    detail, _ = await _detail_cached(symbol)

    async def fetch() -> dict[str, Any]:
        return sim.build_orderbook(symbol, detail["price"], detail["volume"])

    data, hit = await _cached(f"orderbook:{symbol}", config.ORDERBOOK_TTL, fetch)
    _mark(response, hit)
    return data


@router.get("/stocks/{symbol}/investors")
async def stock_investors(symbol: str, response: Response) -> dict[str, Any]:
    """SIMULATED 10-day investor flows — deterministic per (symbol, date)."""
    _require_known(symbol)
    detail, _ = await _detail_cached(symbol)

    async def fetch() -> dict[str, Any]:
        return sim.build_investor_flows(symbol, detail["volume"])

    data, hit = await _cached(f"investors:{symbol}", config.INVESTORS_TTL, fetch)
    _mark(response, hit)
    return data


@router.get("/stocks/{symbol}/news")
async def stock_news(symbol: str, response: Response) -> dict[str, Any]:
    """REAL Yahoo Finance RSS headlines. Upstream failure degrades to an
    empty list + error field (never 500) and is NOT cached."""
    _require_known(symbol)
    try:
        data, hit = await _cached(f"news:{symbol}", config.NEWS_TTL,
                                  lambda: news_svc.fetch_news(symbol))
    except Exception as exc:  # noqa: BLE001
        log.error("news[%s] fetch failed: %r", symbol, exc)
        data, hit = {"symbol": symbol, "items": [],
                     "error": type(exc).__name__}, False
    _mark(response, hit)
    return data


@router.post("/ai/stocks/{symbol}")
async def ai_analyze(symbol: str) -> StreamingResponse:
    _require_known(symbol)
    if not ai.token_present():
        # 503 BEFORE any streaming — AI panel shows disabled state
        raise HTTPException(status_code=503, detail="AWS_BEARER_TOKEN_BEDROCK not set")
    detail, _ = await _detail_cached(symbol)
    return StreamingResponse(
        ai.analyze_stream(detail),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class ArticleBody(BaseModel):
    title: str
    text: str | None = None
    link: str | None = None


@router.post("/ai/articles")
async def ai_article(body: ArticleBody) -> StreamingResponse:
    """Article analysis SSE. Content is never logged (see services/ai.py)."""
    # input-size check first (413 is observable even without a token) …
    combined = len(body.title) + len(body.text or "") + len(body.link or "")
    if combined > config.ARTICLE_MAX_INPUT_CHARS:
        raise HTTPException(status_code=413, detail="article input too large")
    # … then 503 BEFORE any streaming — same contract as /ai/stocks
    if not ai.token_present():
        raise HTTPException(status_code=503, detail="AWS_BEARER_TOKEN_BEDROCK not set")
    return StreamingResponse(
        ai.article_stream(body.title, body.text, body.link),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

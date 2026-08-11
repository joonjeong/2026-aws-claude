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
from labkit.poller import PollingCollector
from pydantic import BaseModel

from ....archive import archive_snapshot
from ..core import config, hours
from ..services import ai, charts, kr, sim, us
from ..services import news as news_svc

log = logging.getLogger("market.api")
router = APIRouter()
cache = TTLCache()
_last_fetch: dict[str, float] = {}  # cache key -> unix time of last upstream fetch

# 이력 아카이브 대상 — 대시보드 3키만 (상세/차트는 심볼×레인지로 증가량 과다)
_ARCHIVE_KEYS = {"overview", "quotes:us", "quotes:kr"}

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
        value = await fetch()
        if key in _ARCHIVE_KEYS:
            # 상류 fetch당 정확히 1회 (워밍 폴러·사용자 요청 무관), best-effort
            archive_snapshot("market", key, value)
        return value

    value = await cache.get_or_fetch(key, ttl_s, wrapped)
    return value, not fetched


# ── 워밍 폴러 — 대시보드 3개 키(overview/quotes:*)만 미리 데운다 ──────────
# 틱마다 라우트와 같은 _cached() 경로를 지나므로: 캐시가 신선하면 딕셔너리
# 조회로 끝(상류 호출 0), 만료 시에만 상류 fetch. 즉 상류 호출 빈도는
# 시장시간 인지 TTL이 그대로 지배하고, 폴러는 만료 직후 공백만 메운다.
# 종목 상세·차트는 심볼 수 × 레인지만큼 호출이 늘어나므로 워밍하지 않는다.
def _warm_tick(key: str, ttl_fn: Callable[[], int],
               fetch: Callable[[], Awaitable[Any]]) -> Callable[[], Awaitable[Any]]:
    async def tick() -> Any:
        value, _hit = await _cached(key, ttl_fn(), fetch)
        return value

    return tick


warm_pollers: list[PollingCollector] = [] if config.WARM_INTERVAL <= 0 else [
    PollingCollector("market-overview", config.WARM_INTERVAL,
                     _warm_tick("overview", hours.overview_ttl, us.fetch_overview)),
    PollingCollector("market-quotes-us", config.WARM_INTERVAL,
                     _warm_tick("quotes:us", lambda: hours.quote_ttl("US"),
                                us.fetch_us_quotes)),
    PollingCollector("market-quotes-kr", config.WARM_INTERVAL,
                     _warm_tick("quotes:kr", lambda: hours.quote_ttl("KR"),
                                kr.fetch_kr_quotes)),
]


def health_info() -> dict[str, Any]:
    """Module health: warm pollers + cache keys and last upstream fetches."""
    now = time.time()
    cached_keys = sorted(
        k for k, (exp, _) in cache._data.items() if exp > now  # noqa: SLF001
    )
    return {
        "status": "ok",
        "ai_token": ai.token_present(),
        "cache_entries": len(cached_keys),
        "cached_keys": cached_keys,
        "last_fetch": {
            k: round(now - t, 1) for k, t in sorted(_last_fetch.items())
        },  # seconds ago
        "pollers": [p.status for p in warm_pollers],
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


@router.get("/indices/spark")
async def indices_spark(response: Response) -> dict[str, Any]:
    """1-month closes for the 5 indices (home dashboard sparklines).
    Cached under one key; TTL follows the 1m chart tier."""
    try:
        data, hit = await _cached("spark:indices", config.CHART_TTL["1m"],
                                  charts.fetch_index_spark)
    except Exception as exc:  # noqa: BLE001
        log.error("indices spark fetch failed: %r", exc)
        raise HTTPException(status_code=502, detail="upstream data source failed")
    _mark(response, hit)
    return data


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


@router.post("/ai/market")
async def ai_market_summary() -> StreamingResponse:
    """전체 시황 요약 SSE — 지수·지표·양시장 시세를 모아 5분 버킷으로 요약.
    같은 버킷의 재요청은 ai 서비스가 캐시를 즉시 final로 재생한다."""
    if not ai.token_present():
        # 503 BEFORE any streaming — 대시보드 패널이 비활성 상태를 표시
        raise HTTPException(status_code=503, detail="AWS_BEARER_TOKEN_BEDROCK not set")
    try:
        # 워밍 폴러와 같은 캐시 키를 지나므로 대부분 딕셔너리 조회로 끝난다
        overview, _ = await _cached("overview", hours.overview_ttl(), us.fetch_overview)
        us_rows, _ = await _cached("quotes:us", hours.quote_ttl("US"), us.fetch_us_quotes)
        kr_rows, _ = await _cached("quotes:kr", hours.quote_ttl("KR"), kr.fetch_kr_quotes)
    except Exception as exc:  # noqa: BLE001
        log.error("ai market summary inputs failed: %r", exc)
        raise HTTPException(status_code=502, detail="upstream data source failed")
    return StreamingResponse(
        ai.market_summary_stream(overview, us_rows, kr_rows),
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

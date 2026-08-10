"""KR quotes via pykrx (synchronous — always call through asyncio.to_thread).

Note: pykrx's market-wide snapshot (get_market_ohlcv(date, market=...)) now
requires a KRX portal login (KRX_ID/KRX_PW) and fails without it, so quotes
are fetched per-ticker via get_market_ohlcv_by_date (works without login),
concurrently with a bounded semaphore. Per-symbol failure skips that symbol.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any

from pykrx import stock

from ..core import config

log = logging.getLogger("market.kr")

_CONCURRENCY = 8


def _quote_row(code: str, name: str) -> dict[str, Any]:
    end = date.today()
    start = end - timedelta(days=14)  # enough calendar days for 2+ trading days
    df = stock.get_market_ohlcv_by_date(start.strftime("%Y%m%d"),
                                        end.strftime("%Y%m%d"), code)
    if df is None or df.empty:
        raise ValueError("empty ohlcv")
    close = float(df["종가"].iloc[-1])
    prev = float(df["종가"].iloc[-2]) if len(df) >= 2 else close
    return {
        "symbol": code,
        "name": name,
        "price": close,
        "change": round(close - prev, 2),
        "change_pct": round((close - prev) / prev * 100, 2) if prev else 0.0,
        "volume": int(df["거래량"].iloc[-1]),
    }


async def fetch_kr_quotes() -> list[dict[str, Any]]:
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def one(code: str, name: str) -> dict[str, Any] | None:
        async with sem:
            try:  # per-symbol failure skips that symbol, never the batch
                return await asyncio.to_thread(_quote_row, code, name)
            except Exception as exc:  # noqa: BLE001
                log.warning("KR symbol %s skipped: %s", code, exc)
                return None

    results = await asyncio.gather(*(one(c, n) for c, n in config.ACTIVE_KR))
    rows = [r for r in results if r is not None]
    if not rows:
        raise RuntimeError("all KR symbols failed")
    return rows


def is_kr_symbol(symbol: str) -> bool:
    return len(symbol) == 6 and symbol.isdigit()


def kr_name(symbol: str) -> str:
    for code, name in config.KR_SYMBOLS:
        if code == symbol:
            return name
    try:
        return stock.get_market_ticker_name(symbol) or symbol
    except Exception:  # noqa: BLE001
        return symbol

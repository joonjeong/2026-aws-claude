"""US quotes / indices / indicators via yfinance (synchronous — always call
through asyncio.to_thread so the event loop never blocks)."""
from __future__ import annotations

import asyncio
import logging
import math
from typing import Any

import yfinance as yf

from ..core import config

log = logging.getLogger("market.us")


def _last_two_closes(df) -> tuple[float, float, int]:
    """(last_close, prev_close, last_volume) from a daily OHLCV frame."""
    closes = df["Close"].dropna()
    if closes.empty:
        raise ValueError("no close data")
    last = float(closes.iloc[-1])
    prev = float(closes.iloc[-2]) if len(closes) >= 2 else last
    vol = 0
    if "Volume" in df:
        vols = df["Volume"].dropna()
        if not vols.empty:
            v = vols.iloc[-1]
            vol = 0 if (isinstance(v, float) and math.isnan(v)) else int(v)
    return last, prev, vol


def _bulk_download(tickers: list[str]):
    """Bulk daily download; group_by ticker so per-symbol frames are separable."""
    return yf.download(
        tickers=" ".join(tickers),
        period="5d",
        interval="1d",
        group_by="ticker",
        threads=True,
        progress=False,
        auto_adjust=False,
    )


def _quote_rows(tickers: list[tuple[str, str]]) -> list[dict[str, Any]]:
    data = _bulk_download([t for t, _ in tickers])
    rows: list[dict[str, Any]] = []
    for symbol, name in tickers:
        try:  # per-symbol failure skips that symbol, never the batch
            # MultiIndex columns when multiple tickers; flat frame otherwise
            df = data[symbol] if symbol in getattr(data.columns, "levels", [[]])[0] else data
            last, prev, vol = _last_two_closes(df)
            change = last - prev
            rows.append({
                "symbol": symbol,
                "name": name,
                "price": round(last, 2),
                "change": round(change, 2),
                "change_pct": round((change / prev * 100) if prev else 0.0, 2),
                "volume": vol,
            })
        except Exception as exc:  # noqa: BLE001
            log.warning("US symbol %s skipped: %s", symbol, exc)
    return rows


async def fetch_us_quotes() -> list[dict[str, Any]]:
    return await asyncio.to_thread(_quote_rows, config.ACTIVE_US)


def _overview_sync() -> dict[str, Any]:
    indices = _quote_rows([(t, n) for t, n, _ in config.INDICES])
    market_by_ticker = {t: m for t, _, m in config.INDICES}
    for row in indices:
        row["market"] = market_by_ticker.get(row["symbol"], "US")
    indicators = _quote_rows(config.INDICATORS)
    return {"indices": indices, "indicators": indicators}


async def fetch_overview() -> dict[str, Any]:
    return await asyncio.to_thread(_overview_sync)

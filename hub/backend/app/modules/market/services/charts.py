"""OHLC chart data + stock detail (header, period returns, 52-week range).

US symbols → yfinance, KR 6-digit codes → pykrx. Both sync libs — every
upstream call goes through asyncio.to_thread.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any

import yfinance as yf
from pykrx import stock

from ..core import config
from .kr import is_kr_symbol, kr_name

log = logging.getLogger("market.charts")

RANGES = ("1w", "1m", "3m", "1y")
_RANGE_DAYS = {"1w": 7, "1m": 31, "3m": 92, "1y": 366}
_YF_PERIOD = {"1w": "7d", "1m": "1mo", "3m": "3mo", "1y": "1y"}


def _us_name(symbol: str) -> str:
    for s, n in config.US_SYMBOLS:
        if s == symbol:
            return n
    for s, n, _ in config.INDICES:
        if s == symbol:
            return n
    return symbol


def _candles_us(symbol: str, rng: str) -> list[dict[str, Any]]:
    df = yf.Ticker(symbol).history(period=_YF_PERIOD[rng], interval="1d",
                                   auto_adjust=False)
    out = []
    for ts, row in df.iterrows():
        try:
            out.append({
                "time": ts.strftime("%Y-%m-%d"),
                "open": round(float(row["Open"]), 4),
                "high": round(float(row["High"]), 4),
                "low": round(float(row["Low"]), 4),
                "close": round(float(row["Close"]), 4),
                "volume": int(row["Volume"]) if row["Volume"] == row["Volume"] else 0,
            })
        except Exception as exc:  # noqa: BLE001
            log.warning("US candle row %s/%s skipped: %s", symbol, ts, exc)
    return out


def _candles_kr(symbol: str, rng: str) -> list[dict[str, Any]]:
    end = date.today()
    start = end - timedelta(days=_RANGE_DAYS[rng])
    df = stock.get_market_ohlcv_by_date(start.strftime("%Y%m%d"),
                                        end.strftime("%Y%m%d"), symbol)
    out = []
    for ts, row in df.iterrows():
        try:
            out.append({
                "time": ts.strftime("%Y-%m-%d"),
                "open": float(row["시가"]),
                "high": float(row["고가"]),
                "low": float(row["저가"]),
                "close": float(row["종가"]),
                "volume": int(row["거래량"]),
            })
        except Exception as exc:  # noqa: BLE001
            log.warning("KR candle row %s/%s skipped: %s", symbol, ts, exc)
    return out


def _candles(symbol: str, rng: str) -> list[dict[str, Any]]:
    return _candles_kr(symbol, rng) if is_kr_symbol(symbol) else _candles_us(symbol, rng)


async def fetch_chart(symbol: str, rng: str) -> dict[str, Any]:
    candles = await asyncio.to_thread(_candles, symbol, rng)
    return {"symbol": symbol, "range": rng, "candles": candles}


def _spark_sync() -> dict[str, Any]:
    """1-month daily closes for every index — one bulk yfinance download.

    KOSPI/KOSDAQ(^KS11/^KQ11)도 yfinance 티커라 US 인덱스와 같은 경로를 탄다.
    per-symbol failure skips that index, never the batch (quotes와 동일 규약).
    """
    tickers = [t for t, _, _ in config.INDICES]
    data = yf.download(
        tickers=" ".join(tickers),
        period="1mo",
        interval="1d",
        group_by="ticker",
        threads=True,
        progress=False,
        auto_adjust=False,
    )
    out: list[dict[str, Any]] = []
    for symbol, name, market in config.INDICES:
        try:
            df = data[symbol] if symbol in getattr(data.columns, "levels", [[]])[0] else data
            closes = df["Close"].dropna()
            if closes.empty:
                raise ValueError("no close data")
            out.append({
                "symbol": symbol,
                "name": name,
                "market": market,
                "points": [
                    [ts.strftime("%Y-%m-%d"), round(float(v), 2)]
                    for ts, v in closes.items()
                ],
            })
        except Exception as exc:  # noqa: BLE001
            log.warning("index spark %s skipped: %s", symbol, exc)
    return {"indices": out}


async def fetch_index_spark() -> dict[str, Any]:
    return await asyncio.to_thread(_spark_sync)


def _return_pct(closes: list[float], days: int) -> float | None:
    """Return over the last ~`days` calendar days using trading-day count."""
    if len(closes) < 2:
        return None
    # ~5 trading days per 7 calendar days
    n = max(1, min(len(closes) - 1, round(days * 5 / 7)))
    base = closes[-1 - n]
    return round((closes[-1] - base) / base * 100, 2) if base else None


def _detail_sync(symbol: str) -> dict[str, Any]:
    candles = _candles(symbol, "1y")  # one 1y fetch feeds header/returns/52w
    if not candles:
        raise LookupError(f"no data for symbol {symbol}")
    closes = [c["close"] for c in candles]
    last, prev = closes[-1], (closes[-2] if len(closes) >= 2 else closes[-1])
    change = last - prev
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    hi52, lo52 = max(highs), min(lows)
    name = kr_name(symbol) if is_kr_symbol(symbol) else _us_name(symbol)
    return {
        "symbol": symbol,
        "name": name,
        "market": "KR" if is_kr_symbol(symbol) else "US",
        "price": round(last, 4),
        "change": round(change, 4),
        "change_pct": round((change / prev * 100) if prev else 0.0, 2),
        "volume": candles[-1]["volume"],
        "returns": {
            "1w": _return_pct(closes, 7),
            "1m": _return_pct(closes, 30),
            "3m": _return_pct(closes, 91),
            "1y": _return_pct(closes, 365),
        },
        "week52": {
            "high": hi52,
            "low": lo52,
            "position": round((last - lo52) / (hi52 - lo52), 4) if hi52 > lo52 else 0.5,
        },
        "as_of": candles[-1]["time"],
    }


async def fetch_detail(symbol: str) -> dict[str, Any]:
    return await asyncio.to_thread(_detail_sync, symbol)

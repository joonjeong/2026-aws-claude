"""yfinance — Yahoo Finance 상류. 생산 kind:
market_overview(지수 5+지표 11) + market_quotes_us(활성 20종목).

이식 원본: hub/backend/app/modules/market/services/us.py. import 금지.
수집 대상(심볼·지수·지표)은 market_symbols.toml이 관리한다.
yfinance는 비공식 라이브러리 — 권장 스케줄(장중 45s/장외 600s)로
hub와 합산 호출량을 관리한다 (케이던스는 오케스트레이터 소유).
"""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Any

from ..core.source import Record

log = logging.getLogger("datalake.yfinance")

KINDS = ("market_overview", "market_quotes_us")

# 수집 대상은 market_symbols.toml이 관리 — 목록 편집 = 코드 무변경
from .market_symbols import ACTIVE_US, INDICES, INDICATORS, US_SYMBOLS  # noqa: F401,E402

# ── hub services/us.py 이식 — import는 함수 내부(extra 격리) ─────────
def _last_two_closes(df) -> tuple[float, float, int]:
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


def _quote_rows(tickers: list[tuple[str, str]]) -> list[dict[str, Any]]:
    import yfinance as yf

    data = yf.download(
        tickers=" ".join(t for t, _ in tickers),
        period="5d", interval="1d", group_by="ticker",
        threads=True, progress=False, auto_adjust=False,
    )
    rows: list[dict[str, Any]] = []
    for symbol, name in tickers:
        try:  # 심볼 단위 격리
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
    return await asyncio.to_thread(_quote_rows, ACTIVE_US)


def _overview_sync() -> dict[str, Any]:
    indices = _quote_rows([(t, n) for t, n, _ in INDICES])
    market_by_ticker = {t: m for t, _, m in INDICES}
    for row in indices:
        row["market"] = market_by_ticker.get(row["symbol"], "US")
    return {"indices": indices, "indicators": _quote_rows(INDICATORS)}


async def fetch_overview() -> dict[str, Any]:
    return await asyncio.to_thread(_overview_sync)


class YFinanceClient:
    id = "yfinance"

    def __init__(self, fetchers: dict | None = None) -> None:
        self._fetchers = fetchers if fetchers is not None else {
            "market_overview": fetch_overview,
            "market_quotes_us": fetch_us_quotes,
        }

    async def fetch(self, kinds: list[str] | None = None) -> list[Record]:
        """요청한(기본 전체) kind를 1회 수집 — kind 단위 실패 격리."""
        records: list[Record] = []
        for kind in (kinds or list(self._fetchers)):
            fetch = self._fetchers.get(kind)
            if fetch is None:
                raise ValueError(f"알 수 없는 kind: {kind} ({list(self._fetchers)})")
            try:
                payload = await fetch()
            except Exception as exc:  # kind 단위 격리
                log.warning("yfinance %s fetch failed: %s: %s",
                            kind, type(exc).__name__, exc)
                continue
            records.append(Record(source=self.id, kind=kind, payload=payload))
        return records


def build() -> YFinanceClient:
    return YFinanceClient()

"""pykrx — KRX 상류. 생산 kind: market_quotes_kr (활성 20종목).

이식 원본: hub/backend/app/modules/market/services/kr.py. import 금지.
수집 대상은 market_symbols.toml이 관리한다. pykrx의 시장 전체 스냅샷은 KRX 포털 로그인이 필요해져
종목당 get_market_ohlcv_by_date 경로 사용 (세마포어 8, hub와 동일).
권장 스케줄: 장중 45s / 장외 600s.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any

from ..core.source import Record

log = logging.getLogger("datalake.pykrx")

KIND = "market_quotes_kr"
_CONCURRENCY = 8

# 수집 대상은 market_symbols.toml이 관리 — 목록 편집 = 코드 무변경
from .market_symbols import ACTIVE_KR, KR_SYMBOLS  # noqa: F401,E402

# ── hub services/kr.py 이식 — import는 함수 내부(extra 격리) ─────────
def _kr_quote_row(code: str, name: str) -> dict[str, Any]:
    from pykrx import stock

    end = date.today()
    start = end - timedelta(days=14)  # 거래일 2일 이상 확보
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
            try:  # 심볼 단위 격리
                return await asyncio.to_thread(_kr_quote_row, code, name)
            except Exception as exc:  # noqa: BLE001
                log.warning("KR symbol %s skipped: %s", code, exc)
                return None

    results = await asyncio.gather(*(one(c, n) for c, n in ACTIVE_KR))
    rows = [r for r in results if r is not None]
    if not rows:
        raise RuntimeError("all KR symbols failed")
    return rows


class PykrxClient:
    id = "pykrx"

    def __init__(self, fetcher=None) -> None:
        self._fetcher = fetcher if fetcher is not None else fetch_kr_quotes

    async def fetch(self) -> list[Record]:
        payload = await self._fetcher()
        return [Record(source=self.id, kind=KIND, payload=payload)]


def build() -> PykrxClient:
    return PykrxClient()

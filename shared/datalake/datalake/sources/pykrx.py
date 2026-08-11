"""pykrx — KRX 상류 (optional extra). 생산 kind: market_quotes_kr (활성 20종목).

이식 원본: hub/backend/app/modules/market/{core/config.py, services/kr.py}.
import 금지. pykrx의 시장 전체 스냅샷은 KRX 포털 로그인이 필요해져
종목당 get_market_ohlcv_by_date 경로 사용 (세마포어 8, hub와 동일).
권장 스케줄: 장중 45s / 장외 600s.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any

from ..core.env import env_int
from ..core.source import Record

log = logging.getLogger("datalake.pykrx")

KIND = "market_quotes_kr"
_CONCURRENCY = 8

# hub market core/config.py 값 복사 — KR 50, 목록 순서 고정
KR_SYMBOLS: list[tuple[str, str]] = [
    ("005930", "삼성전자"), ("000660", "SK하이닉스"), ("373220", "LG에너지솔루션"),
    ("005380", "현대차"), ("000270", "기아"), ("207940", "삼성바이오로직스"),
    ("006400", "삼성SDI"), ("035420", "NAVER"), ("035720", "카카오"),
    ("005490", "POSCO홀딩스"), ("068270", "셀트리온"), ("028260", "삼성물산"),
    ("105560", "KB금융"), ("055550", "신한지주"), ("012330", "현대모비스"),
    ("066570", "LG전자"), ("003670", "포스코퓨처엠"), ("051910", "LG화학"),
    ("096770", "SK이노베이션"), ("034730", "SK"), ("000810", "삼성화재"),
    ("003550", "LG"), ("032830", "삼성생명"), ("009150", "삼성전기"),
    ("086790", "하나금융지주"), ("010130", "고려아연"), ("033780", "KT&G"),
    ("011200", "HMM"), ("247540", "에코프로비엠"), ("377300", "카카오페이"),
    ("030200", "KT"), ("017670", "SK텔레콤"), ("018260", "삼성에스디에스"),
    ("036570", "엔씨소프트"), ("316140", "우리금융지주"), ("003490", "HD한국조선해양"),
    ("034020", "두산에너빌리티"), ("011170", "롯데케미칼"), ("024110", "기업은행"),
    ("010950", "S-Oil"), ("006800", "미래에셋증권"), ("004020", "현대제철"),
    ("000720", "현대건설"), ("002790", "아모레G"), ("138040", "메리츠금융지주"),
    ("259960", "크래프톤"), ("326030", "SK바이오팜"), ("323410", "카카오뱅크"),
    ("361610", "SK아이이테크놀로지"), ("352820", "하이브"),
]

ACTIVE_KR = KR_SYMBOLS[:env_int("DATALAKE_MARKET_ACTIVE_KR", 20)]


# ── hub services/kr.py 이식 — import는 함수 내부(extra 격리) ─────────
def _kr_quote_row(code: str, name: str) -> dict[str, Any]:
    from pykrx import stock  # market extra

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


def build() -> PykrxClient | None:
    try:
        import pykrx  # noqa: F401
    except ImportError:
        log.info("pykrx 비활성: market extra 미설치 "
                 "(uv sync --extra market 후 사용 가능)")
        return None
    return PykrxClient()

"""market — 미·한 시세 클라이언트 (yfinance·pykrx, optional extra).

이식 원본: hub/backend/app/modules/market/{core/config.py, services/us.py,
services/kr.py}. import 금지.

- kinds: overview(지수 5+지표 11), quotes_us(활성 20), quotes_kr(활성 20)
- payload는 hub가 snapshots에 남기는 것과 동형의 시세 행 구조
- yfinance/pykrx 미설치(base install) 시 build()가 None
- 케이던스는 오케스트레이터 소유 — hub 실효 주기(장중 45s/장외 600s)를
  Temporal 스케줄로 재현할 것 (비공식 라이브러리 호출량 배려, README 참조)
"""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import date, timedelta
from typing import Any, Awaitable, Callable

from ..core.env import env_int
from ..core.source import Record

log = logging.getLogger("datalake.market")

KINDS = ("overview", "quotes_us", "quotes_kr")
_KR_CONCURRENCY = 8

# hub market core/config.py 값 복사 — US 50 + KR 50, 목록 순서 고정
US_SYMBOLS: list[tuple[str, str]] = [
    ("AAPL", "Apple"), ("MSFT", "Microsoft"), ("GOOGL", "Alphabet"),
    ("AMZN", "Amazon"), ("NVDA", "NVIDIA"), ("META", "Meta Platforms"),
    ("TSLA", "Tesla"), ("BRK-B", "Berkshire Hathaway"), ("JPM", "JPMorgan Chase"),
    ("V", "Visa"), ("JNJ", "Johnson & Johnson"), ("UNH", "UnitedHealth"),
    ("WMT", "Walmart"), ("MA", "Mastercard"), ("PG", "Procter & Gamble"),
    ("HD", "Home Depot"), ("XOM", "Exxon Mobil"), ("CVX", "Chevron"),
    ("LLY", "Eli Lilly"), ("ABBV", "AbbVie"), ("PFE", "Pfizer"),
    ("KO", "Coca-Cola"), ("PEP", "PepsiCo"), ("MRK", "Merck"),
    ("COST", "Costco"), ("AVGO", "Broadcom"), ("AMD", "AMD"),
    ("ORCL", "Oracle"), ("CRM", "Salesforce"), ("NFLX", "Netflix"),
    ("ADBE", "Adobe"), ("CSCO", "Cisco"), ("ACN", "Accenture"),
    ("TXN", "Texas Instruments"), ("INTC", "Intel"), ("QCOM", "Qualcomm"),
    ("INTU", "Intuit"), ("AMAT", "Applied Materials"), ("BKNG", "Booking Holdings"),
    ("ISRG", "Intuitive Surgical"), ("MDLZ", "Mondelez"), ("ADP", "ADP"),
    ("REGN", "Regeneron"), ("VRTX", "Vertex Pharmaceuticals"), ("GILD", "Gilead Sciences"),
    ("PANW", "Palo Alto Networks"), ("LRCX", "Lam Research"), ("MU", "Micron"),
    ("KLAC", "KLA"), ("SNPS", "Synopsys"),
]

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

ACTIVE_US = US_SYMBOLS[:env_int("DATALAKE_MARKET_ACTIVE_US", 20)]
ACTIVE_KR = KR_SYMBOLS[:env_int("DATALAKE_MARKET_ACTIVE_KR", 20)]

INDICES: list[tuple[str, str, str]] = [  # (yf ticker, display name, market)
    ("^GSPC", "S&P 500", "US"),
    ("^IXIC", "NASDAQ", "US"),
    ("^DJI", "Dow Jones", "US"),
    ("^KS11", "KOSPI", "KR"),
    ("^KQ11", "KOSDAQ", "KR"),
]

INDICATORS: list[tuple[str, str]] = [
    ("CL=F", "WTI유"), ("GC=F", "금"), ("SI=F", "은"), ("HG=F", "구리"),
    ("EURUSD=X", "EUR/USD"), ("KRW=X", "USD/KRW"), ("JPY=X", "USD/JPY"),
    ("CNY=X", "USD/CNY"), ("^TNX", "미 10년물"),
    ("BTC-USD", "비트코인"), ("ETH-USD", "이더리움"),
]


# ── yfinance (US) — hub services/us.py 이식, import는 함수 내부(extra 격리) ──
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
    import yfinance as yf  # market extra

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


# ── pykrx (KR) — hub services/kr.py 이식 ─────────────────────────────
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
    sem = asyncio.Semaphore(_KR_CONCURRENCY)

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


# ── 클라이언트 ────────────────────────────────────────────────────────
class MarketClient:
    id = "market"

    def __init__(
        self,
        fetchers: dict[str, Callable[[], Awaitable[Any]]] | None = None,
    ) -> None:
        self._fetchers = fetchers if fetchers is not None else {
            "overview": fetch_overview,
            "quotes_us": fetch_us_quotes,
            "quotes_kr": fetch_kr_quotes,
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
                log.warning("market %s fetch failed: %s: %s",
                            kind, type(exc).__name__, exc)
                continue
            records.append(Record(source=self.id, kind=kind, payload=payload))
        return records


def build() -> MarketClient | None:
    try:
        import pykrx  # noqa: F401
        import yfinance  # noqa: F401
    except ImportError:
        log.info("market 비활성: market extra 미설치 "
                 "(uv sync --extra market 후 사용 가능)")
        return None
    return MarketClient()

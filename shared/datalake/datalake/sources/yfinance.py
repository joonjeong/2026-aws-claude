"""yfinance — Yahoo Finance 상류 (optional extra). 생산 kind:
market_overview(지수 5+지표 11) + market_quotes_us(활성 20종목).

이식 원본: hub/backend/app/modules/market/{core/config.py, services/us.py}.
import 금지. yfinance는 비공식 라이브러리 — 권장 스케줄(장중 45s/장외 600s)로
hub와 합산 호출량을 관리한다 (케이던스는 오케스트레이터 소유).
"""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Any

from ..core.env import env_int
from ..core.source import Record

log = logging.getLogger("datalake.yfinance")

KINDS = ("market_overview", "market_quotes_us")

# hub market core/config.py 값 복사 — US 50, 목록 순서 고정
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

ACTIVE_US = US_SYMBOLS[:env_int("DATALAKE_MARKET_ACTIVE_US", 20)]

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


def build() -> YFinanceClient | None:
    try:
        import yfinance  # noqa: F401
    except ImportError:
        log.info("yfinance 비활성: market extra 미설치 "
                 "(uv sync --extra market 후 사용 가능)")
        return None
    return YFinanceClient()

import importlib.util

import pytest

from datalake.sources import pykrx, yfinance


async def test_yfinance_fetch_requested_kinds():
    calls = {"market_overview": 0, "market_quotes_us": 0}

    async def fetch_overview():
        calls["market_overview"] += 1
        return {"indices": [], "indicators": []}

    async def fetch_us():
        calls["market_quotes_us"] += 1
        return [{"symbol": "AAPL"}]

    client = yfinance.YFinanceClient(
        fetchers={"market_overview": fetch_overview,
                  "market_quotes_us": fetch_us})

    recs = await client.fetch(["market_overview"])
    assert [(r.source, r.kind) for r in recs] == [("yfinance", "market_overview")]
    assert calls == {"market_overview": 1, "market_quotes_us": 0}  # 요청 kind만

    recs = await client.fetch()  # 기본: 전체
    assert [r.kind for r in recs] == ["market_overview", "market_quotes_us"]


async def test_yfinance_isolates_kind_failure():
    async def bad():
        raise RuntimeError("upstream")

    async def good():
        return [{"symbol": "AAPL"}]

    client = yfinance.YFinanceClient(
        fetchers={"market_overview": bad, "market_quotes_us": good})
    recs = await client.fetch()
    assert [r.kind for r in recs] == ["market_quotes_us"]  # 실패 kind만 빠짐


async def test_yfinance_unknown_kind_raises():
    client = yfinance.YFinanceClient(fetchers={})
    with pytest.raises(ValueError):
        await client.fetch(["nope"])


async def test_pykrx_fetch():
    async def fake():
        return [{"symbol": "005930", "price": 70000.0}]

    (rec,) = await pykrx.PykrxClient(fetcher=fake).fetch()
    assert rec.source == "pykrx" and rec.kind == "market_quotes_kr"
    assert rec.payload[0]["symbol"] == "005930"


# ── 심볼 유니버스 (hub 값 복사 검증) ──────────────────────────
def test_symbol_universe():
    assert len(yfinance.US_SYMBOLS) == 50 and len(pykrx.KR_SYMBOLS) == 50
    assert yfinance.ACTIVE_US[0] == ("AAPL", "Apple")
    assert pykrx.ACTIVE_KR[0] == ("005930", "삼성전자")
    assert len(yfinance.ACTIVE_US) == 20 and len(pykrx.ACTIVE_KR) == 20
    assert len(yfinance.INDICES) == 5 and len(yfinance.INDICATORS) == 11


@pytest.mark.skipif(importlib.util.find_spec("yfinance") is not None,
                    reason="market extra 설치 환경에서는 build가 활성")
def test_build_disabled_without_extra():
    assert yfinance.build() is None
    assert pykrx.build() is None

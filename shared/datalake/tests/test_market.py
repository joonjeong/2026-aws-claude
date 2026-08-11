import importlib.util

import pytest

from datalake.sources import market


async def test_fetch_requested_kinds():
    calls = {"overview": 0, "quotes_us": 0}

    async def fetch_overview():
        calls["overview"] += 1
        return {"indices": [], "indicators": []}

    async def fetch_us():
        calls["quotes_us"] += 1
        return [{"symbol": "AAPL"}]

    client = market.MarketClient(
        fetchers={"overview": fetch_overview, "quotes_us": fetch_us})

    recs = await client.fetch(["overview"])
    assert [r.kind for r in recs] == ["overview"]
    assert calls == {"overview": 1, "quotes_us": 0}  # 요청한 kind만 호출

    recs = await client.fetch()  # 기본: 전체
    assert [r.kind for r in recs] == ["overview", "quotes_us"]
    assert all(r.source == "market" for r in recs)


async def test_fetch_isolates_kind_failure():
    async def bad():
        raise RuntimeError("upstream")

    async def good():
        return [{"symbol": "AAPL"}]

    client = market.MarketClient(fetchers={"overview": bad, "quotes_us": good})
    recs = await client.fetch()
    assert [r.kind for r in recs] == ["quotes_us"]  # 실패 kind만 빠짐


async def test_fetch_unknown_kind_raises():
    client = market.MarketClient(fetchers={})
    with pytest.raises(ValueError):
        await client.fetch(["nope"])


# ── 심볼 유니버스 (hub 값 복사 검증) ──────────────────────────
def test_symbol_universe():
    assert len(market.US_SYMBOLS) == 50 and len(market.KR_SYMBOLS) == 50
    assert market.ACTIVE_US[0] == ("AAPL", "Apple")
    assert market.ACTIVE_KR[0] == ("005930", "삼성전자")
    assert len(market.ACTIVE_US) == 20 and len(market.ACTIVE_KR) == 20
    assert len(market.INDICES) == 5 and len(market.INDICATORS) == 11


@pytest.mark.skipif(importlib.util.find_spec("yfinance") is not None,
                    reason="market extra 설치 환경에서는 build가 활성")
def test_build_disabled_without_extra():
    assert market.build() is None

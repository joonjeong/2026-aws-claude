import importlib.util
from datetime import datetime, timezone

import pytest

from datalake.sources import market, market_hours


# ── 장시간 판정 (2026-08-11 = 화요일) ─────────────────────────
def _utc(h, m, day=11):
    return datetime(2026, 8, day, h, m, tzinfo=timezone.utc)


def test_us_market_window():
    # 13:30 UTC = 09:30 EDT 개장 경계
    assert market_hours.us_market_open(_utc(13, 30)) is True
    assert market_hours.us_market_open(_utc(13, 29)) is False
    assert market_hours.us_market_open(_utc(19, 59)) is True   # 15:59 EDT
    assert market_hours.us_market_open(_utc(20, 0)) is False   # 16:00 EDT 폐장
    assert market_hours.us_market_open(_utc(14, 0, day=15)) is False  # 토요일


def test_kr_market_window():
    # 00:00 UTC = 09:00 KST 개장 경계
    assert market_hours.kr_market_open(_utc(0, 0)) is True
    assert market_hours.kr_market_open(_utc(6, 29)) is True    # 15:29 KST
    assert market_hours.kr_market_open(_utc(6, 30)) is False   # 15:30 KST 폐장


def test_ttl_for_overview_either_market():
    open_kr_only = _utc(1, 0)     # KR 장중, US 장외
    closed_both = _utc(21, 0)     # 06:00 KST 익일 전·17:00 EDT 후
    assert market_hours.ttl_for("quotes_kr", open_kr_only) == market_hours.TTL_OPEN
    assert market_hours.ttl_for("quotes_us", open_kr_only) == market_hours.TTL_CLOSED
    assert market_hours.ttl_for("overview", open_kr_only) == market_hours.TTL_OPEN
    assert market_hours.ttl_for("overview", closed_both) == market_hours.TTL_CLOSED


# ── TTL 게이트 ────────────────────────────────────────────────
async def test_tick_gate_limits_upstream_calls(monkeypatch):
    calls = {"overview": 0}

    async def fetch_overview():
        calls["overview"] += 1
        return {"indices": [], "indicators": []}

    src = market.MarketSource(fetchers={"overview": fetch_overview})
    (job,) = src.jobs()
    assert job.name == "market-warm"
    assert job.interval_s == 30.0  # hub MARKET_WARM_INTERVAL

    recs = await job.fetch()
    assert len(recs) == 1 and calls["overview"] == 1
    assert recs[0].source == "market" and recs[0].kind == "overview"

    # TTL(최소 45s) 내 재틱 → 상류 호출 없음
    assert await job.fetch() == []
    assert calls["overview"] == 1

    # 게이트 만료 강제 → 재호출
    src._last["overview"] = 0.0
    assert len(await job.fetch()) == 1
    assert calls["overview"] == 2


async def test_tick_isolates_kind_failure():
    async def bad():
        raise RuntimeError("upstream")

    async def good():
        return [{"symbol": "AAPL"}]

    src = market.MarketSource(fetchers={"overview": bad, "quotes_us": good})
    recs = await src._tick()
    assert [r.kind for r in recs] == ["quotes_us"]  # 실패 kind만 빠짐
    # 실패한 kind는 last 미갱신 → 다음 틱에 재시도 대상
    assert "overview" not in src._last


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

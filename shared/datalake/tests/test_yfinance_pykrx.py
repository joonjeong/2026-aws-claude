import json

import pytest

from datalake import pykrx, yfinance


def test_symbol_lists():
    assert len(yfinance.load_symbols()["us"]["symbols"]) == 50
    assert len(pykrx.load_symbols()["kr"]["symbols"]) == 50
    assert yfinance.active_us()[0] == ("AAPL", "Apple")
    assert pykrx.active_kr()[0] == ("005930", "삼성전자")
    assert len(yfinance.indices()) == 5 and len(yfinance.indicators()) == 11


def test_symbol_list_override(tmp_path, monkeypatch):
    custom = tmp_path / "symbols.toml"
    custom.write_text('[us]\nsymbols = [["TEST", "Test Co"]]\n'
                      '[kr]\nsymbols = [["000001", "테스트"]]\n'
                      '[indices]\nitems = [["^T", "T", "US"]]\n'
                      '[indicators]\nitems = [["X=F", "엑스"]]\n', encoding="utf-8")
    monkeypatch.setenv("DATALAKE_MARKET_SYMBOLS", str(custom))
    assert yfinance.active_us() == [("TEST", "Test Co")]  # 목록 파일 교체
    assert pykrx.active_kr() == [("000001", "테스트")]


def test_yfinance_flatten():
    overview = {"indices": [{"symbol": "^KS11", "name": "KOSPI", "price": 3000.0,
                             "change": 10.0, "change_pct": 0.33, "volume": 0,
                             "market": "KR"}],
                "indicators": [{"symbol": "BTC-USD", "name": "비트코인",
                                "price": 100000.0, "change": -5.0,
                                "change_pct": -0.01, "volume": 123}]}
    rows = yfinance.flatten("market_overview", overview, ts=1000.0)
    assert {(r["kind"], r["symbol"], r.get("market")) for r in rows} \
        == {("index", "^KS11", "KR"), ("indicator", "BTC-USD", None)}
    assert all("market" not in r for r in rows if r["kind"] == "indicator")  # 키 생략

    us = yfinance.flatten("market_quotes_us", [{"symbol": "AAPL"}], ts=1000.0)
    assert us[0]["kind"] == "quote_us" and us[0]["market"] == "US"


async def test_yfinance_collect_with_fake_fetchers(tmp_path):
    calls = []

    def fetch_overview():
        calls.append("overview")
        return {"indices": [], "indicators": [
            {"symbol": "GC=F", "name": "금", "price": 2400.0,
             "change": 1.0, "change_pct": 0.04, "volume": 0}]}

    def bad():
        raise RuntimeError("upstream")

    assert await yfinance.collect(
        tmp_path, fetchers={"market_overview": fetch_overview,
                            "market_quotes_us": bad}) == 0  # kind 격리

    (bronze,) = list(tmp_path.glob("bronze/market_quotes/source=*/dt=*/part-*.jsonl"))
    (row,) = [json.loads(x) for x in bronze.read_text().splitlines()]
    assert row["kind"] == "indicator" and row["symbol"] == "GC=F"
    assert bronze.parts[-3] == "source=yfinance"  # 공급자는 파티션 경로
    assert calls == ["overview"]


async def test_yfinance_unknown_kind_raises(tmp_path):
    with pytest.raises(ValueError):
        await yfinance.collect(tmp_path, kinds=["nope"], fetchers={})


async def test_pykrx_collect_with_fake_fetcher(tmp_path):
    async def fake():
        return [{"symbol": "005930", "name": "삼성전자", "price": 70000.0,
                 "change": 500.0, "change_pct": 0.72, "volume": 1000}]

    assert await pykrx.collect(tmp_path, keep_landing=True, fetcher=fake) == 0
    (bronze,) = list(tmp_path.glob("bronze/market_quotes/source=*/dt=*/part-*.jsonl"))
    (row,) = [json.loads(x) for x in bronze.read_text().splitlines()]
    assert row["kind"] == "quote_kr" and row["market"] == "KR"
    assert row["symbol"] == "005930" and "source" not in row
    assert bronze.parts[-3] == "source=pykrx"
    (landing,) = list(tmp_path.glob("landing/pykrx/market_quotes_kr/dt=*/part-*.jsonl"))
    assert json.loads(landing.read_text())["payload"][0]["price"] == 70000.0

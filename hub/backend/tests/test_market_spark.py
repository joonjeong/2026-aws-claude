"""GET /indices/spark — 홈 대시보드 지수 스파크라인 계약."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.market.api import routes


def _client(monkeypatch) -> TestClient:
    async def fake_fetch():
        return {"indices": [{
            "symbol": "^GSPC", "name": "S&P 500", "market": "US",
            "points": [["2026-07-13", 6000.0], ["2026-08-10", 6120.5]],
        }]}

    monkeypatch.setattr(routes.charts, "fetch_index_spark", fake_fetch)
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app)


def test_spark_shape_and_cache_header(monkeypatch):
    client = _client(monkeypatch)
    r = client.get("/indices/spark")
    assert r.status_code == 200
    assert r.headers["X-Cache"] == "MISS"
    idx = r.json()["indices"][0]
    assert idx["symbol"] == "^GSPC"
    assert idx["points"][-1] == ["2026-08-10", 6120.5]

    # 두 번째 호출은 TTLCache 히트 — 상류 재호출 없음
    r2 = client.get("/indices/spark")
    assert r2.headers["X-Cache"] == "HIT"


def test_spark_upstream_failure_returns_502(monkeypatch):
    async def boom():
        raise RuntimeError("upstream down")

    monkeypatch.setattr(routes.charts, "fetch_index_spark", boom)
    routes.cache._data.pop("spark:indices", None)  # noqa: SLF001 — 캐시 격리
    app = FastAPI()
    app.include_router(routes.router)
    client = TestClient(app)
    assert client.get("/indices/spark").status_code == 502

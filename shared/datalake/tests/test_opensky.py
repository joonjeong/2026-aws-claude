"""opensky 상류 — states 정규화·인증·익명 폴백·kind (adsblol과 수렴)."""

import json

import httpx

from datalake.core.source import Record
from datalake.core.transform import rows_for
from datalake.sources import opensky


def _state(icao="abc123", lon=127.0, lat=37.5):
    # 0 icao24, 1 callsign, 2 origin_country, 3 time_position, 4 last_contact,
    # 5 lon, 6 lat, 7 baro_alt(m), 8 on_ground, 9 velocity(m/s), 10 track
    return [icao, "KAL123 ", "South Korea", 1786430000, 1786430005,
            lon, lat, 3048.0, False, 205.0, 90.0]


def test_normalize_states():
    payload = {"states": [
        _state(),
        [None, "", None, None, None, None, None] + [None] * 4,  # icao 없음 → 스킵
        "junk",                                                  # 기형 → 격리
    ]}
    rows = opensky.normalize(payload, now=1000.0)
    assert len(rows) == 1
    s = rows[0]
    assert s["id"] == "abc123" and s["callsign"] == "KAL123"
    assert s["origin_country"] == "South Korea"
    assert s["alt_m"] == 3048.0          # 이미 미터계 — 변환 없음
    assert s["velocity_ms"] == 205.0
    assert s["ts"] == 1786430000.0       # time_position 우선
    assert s["type"] is None and s["reg"] is None


async def test_fetch_auth_kind_and_token_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(opensky, "REGION_SPACING_S", 0.0)
    monkeypatch.setenv("DATALAKE_OPENSKY_CLIENT_ID", "cid")
    monkeypatch.setenv("DATALAKE_OPENSKY_CLIENT_SECRET", "sec")
    token_calls = []
    lamins = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "openid-connect/token" in url:
            token_calls.append(request.read().decode())
            return httpx.Response(200, json={"access_token": "TOK",
                                             "expires_in": 1800})
        assert request.headers["authorization"] == "Bearer TOK"
        lamins.append(request.url.params.get("lamin"))
        return httpx.Response(200, json={"states": [_state()]})

    state = tmp_path / "opensky_token.json"
    client = opensky.OpenSkyClient(state_path=state,
                                   transport=httpx.MockTransport(handler))

    (rec,) = await client.fetch_global()
    assert rec.source == "opensky"
    assert rec.kind == "contrail_global"      # adsblol과 같은 kind로 수렴
    assert "grant_type=client_credentials" in token_calls[0]

    recs = await client.fetch_regions()
    assert recs[0].kind == "contrail_region_kr"
    assert lamins == [None, "30.0", "30.0", "43.0", "25.0"]  # 전세계 무파라미터 + 프리셋 4개
    # 토큰은 상태 파일 캐시로 재사용 — 재발급 없음 (one-shot 간에도 이어짐)
    assert len(token_calls) == 1
    assert json.loads(state.read_text())["access_token"] == "TOK"
    # 자격증명 파일은 소유자 전용 (0600)
    assert (state.stat().st_mode & 0o777) == 0o600

    fresh = opensky.OpenSkyClient(state_path=state)
    assert fresh._read_cached_token() == "TOK"


async def test_anonymous_fallback(monkeypatch):
    monkeypatch.delenv("DATALAKE_OPENSKY_CLIENT_ID", raising=False)
    monkeypatch.delenv("DATALAKE_OPENSKY_CLIENT_SECRET", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        assert "openid-connect" not in str(request.url)  # 토큰 요청 없음
        assert "authorization" not in request.headers
        return httpx.Response(200, json={"states": []})

    client = opensky.OpenSkyClient(transport=httpx.MockTransport(handler))
    (rec,) = await client.fetch_global()
    assert rec.payload == {"states": []}


def test_transform_merges_providers_into_same_table():
    readsb_rec = Record(source="adsblol", kind="contrail_region_kr",
                        fetched_at=1000.0, meta={},
                        payload={"ac": [{"hex": "aaa", "lat": 37.0, "lon": 127.0}]})
    opensky_rec = Record(source="opensky", kind="contrail_region_kr",
                         fetched_at=1000.0, meta={},
                         payload={"states": [_state(icao="bbb")]})
    global_rec = Record(source="opensky", kind="contrail_global",
                        fetched_at=1000.0, meta={}, payload={"states": []})

    t1 = rows_for(readsb_rec)["contrail_positions"]
    t2 = rows_for(opensky_rec)["contrail_positions"]
    assert {r["icao24"] for r in t1} == {"aaa"}
    assert {r["icao24"] for r in t2} == {"bbb"}
    assert set(t1[0]) == set(t2[0])       # 두 상류가 같은 컬럼으로 수렴
    assert rows_for(global_rec) == {}      # 전세계 스냅샷은 제외 (양 상류)

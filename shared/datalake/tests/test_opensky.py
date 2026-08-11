import json

import httpx

from datalake import opensky


def _state(icao="abc123", lon=127.0, lat=37.5):
    # 0 icao24, 1 callsign, 2 origin_country, 3 time_position, 4 last_contact,
    # 5 lon, 6 lat, 7 baro_alt(m), 8 on_ground, 9 velocity(m/s), 10 track
    return [icao, "KAL123 ", "South Korea", 1786430000, 1786430005,
            lon, lat, 3048.0, False, 205.0, 90.0]


def test_parse_states():
    rows = opensky.parse({"states": [
        _state(),
        [None, "", None, None, None, None, None] + [None] * 4,  # icao 없음 → 필터
        "junk",                                                  # 기형 → 격리
    ]}, now=1000.0)
    assert len(rows) == 1
    s = rows[0]
    assert s["id"] == "abc123" and s["callsign"] == "KAL123"
    assert s["origin_country"] == "South Korea"
    assert s["alt_m"] == 3048.0          # 이미 미터계 — 변환 없음
    assert s["ts"] == 1786430000.0       # time_position 우선


async def test_collect_auth_token_cache_and_zones(tmp_path, monkeypatch):
    monkeypatch.setattr(opensky, "REGION_SPACING_S", 0.0)
    monkeypatch.setenv("DATALAKE_OPENSKY_CLIENT_ID", "cid")
    monkeypatch.setenv("DATALAKE_OPENSKY_CLIENT_SECRET", "sec")
    token_calls, lamins = [], []

    def handler(request: httpx.Request) -> httpx.Response:
        if "openid-connect/token" in str(request.url):
            token_calls.append(request.read().decode())
            return httpx.Response(200, json={"access_token": "TOK",
                                             "expires_in": 1800})
        assert request.headers["authorization"] == "Bearer TOK"
        lamins.append(request.url.params.get("lamin"))
        return httpx.Response(200, json={"states": [_state()]})

    assert await opensky.collect(tmp_path, "both",
                                 transport=httpx.MockTransport(handler)) == 0
    assert lamins == [None, "30.0", "30.0", "43.0", "25.0"]  # 전세계 무파라미터 + 프리셋 4
    assert len(token_calls) == 1  # 상태 파일 캐시 — 재발급 없음
    assert "grant_type=client_credentials" in token_calls[0]

    state = tmp_path / "_state" / "opensky_token.json"
    assert json.loads(state.read_text())["access_token"] == "TOK"
    assert (state.stat().st_mode & 0o777) == 0o600  # 자격증명 파일 소유자 전용

    kinds = {p.parts[-3] for p in tmp_path.glob("landing/opensky/*/dt=*/part-*.jsonl")}
    assert "contrail_global" in kinds and "contrail_region_kr" in kinds
    # bronze는 adsblol과 같은 테이블로 수렴 (제공자 중립)
    (aircraft,) = list(tmp_path.glob("bronze/contrail_aircraft/source=*/dt=*/part-*.jsonl"))
    rows = [json.loads(x) for x in aircraft.read_text().splitlines()]
    assert all(r["origin_country"] == "South Korea" for r in rows)
    assert aircraft.parts[-3] == "source=opensky"  # 공급자는 파티션 경로
    assert all("source" not in r and "type" not in r for r in rows)


async def test_collect_anonymous_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("DATALAKE_OPENSKY_CLIENT_ID", raising=False)
    monkeypatch.delenv("DATALAKE_OPENSKY_CLIENT_SECRET", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        assert "openid-connect" not in str(request.url)  # 토큰 요청 없음
        assert "authorization" not in request.headers
        return httpx.Response(200, json={"states": []})

    assert await opensky.collect(tmp_path, "global",
                                 transport=httpx.MockTransport(handler)) == 0

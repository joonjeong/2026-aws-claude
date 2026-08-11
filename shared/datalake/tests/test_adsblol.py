import json

import httpx
import pytest

from datalake import adsblol


def test_url_is_raw_unencoded():
    # re-api는 %2C·jv2= 를 400으로 거부 — 원시 쿼리 형식 고정 (hub와 동일)
    assert adsblol.url_for((30.0, 120.0, 45.0, 135.0)) \
        == "https://re-api.adsb.lol/?box=30.0,45.0,120.0,135.0&jv2"


def test_parse_units_and_defense():
    rows = adsblol.parse({"ac": [
        {"hex": "abc123", "flight": "KAL123 ", "lat": 37.5, "lon": 127.0,
         "alt_baro": 10000, "gs": 400, "track": 90, "seen_pos": 2.0,
         "t": "B738", "r": "HL1234"},
        {"hex": "def456", "lat": 35.0, "lon": 129.0, "alt_baro": "ground",
         "calc_track": 180},
        {"hex": "nopos1"},     # 위치 없음 → 필터
        "junk",                # 깨진 항목 → 격리
    ]}, now=1000.0)
    assert len(rows) == 2
    a, g = rows
    assert a["alt_m"] == pytest.approx(10000 * 0.3048)
    assert a["velocity_ms"] == pytest.approx(400 * 0.514444)
    assert a["ts"] == 998.0 and a["callsign"] == "KAL123"
    assert g["on_ground"] is True and g["alt_m"] is None
    assert g["track_deg"] == 180.0  # calc_track 폴백


async def test_collect_zones(tmp_path, monkeypatch):
    monkeypatch.setattr(adsblol, "REGION_SPACING_S", 0.0)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        assert request.headers["user-agent"].startswith("DataLake/0.1")
        return httpx.Response(200, json={"ac": [{"hex": "a", "lat": 1, "lon": 2}]})

    assert await adsblol.collect(tmp_path, "both", keep_landing=True,
                                 transport=httpx.MockTransport(handler)) == 0
    assert "box=-90.0,90.0,-180.0,180.0&jv2" in calls[0]  # 전세계 먼저

    kinds = {p.parts[-3] for p in tmp_path.glob("landing/adsblol/*/dt=*/part-*.jsonl")}
    assert kinds == {"contrail_global", "contrail_region_kr", "contrail_region_japan",
                     "contrail_region_europe", "contrail_region_us-east"}

    # bronze는 지역 4개분만 (전세계는 landing만 — 홍수 방지)
    (positions4,) = list(tmp_path.glob("bronze/contrail_positions/source=*/dt=*/part-*.jsonl"))
    assert len(positions4.read_text().splitlines()) == 4
    (aircraft,) = list(tmp_path.glob("bronze/contrail_aircraft/source=*/dt=*/part-*.jsonl"))
    (row, *_rest) = [json.loads(x) for x in aircraft.read_text().splitlines()]
    assert row["icao24"] == "a" and "first_seen" in row
    assert aircraft.parts[-3] == "source=adsblol"  # 공급자는 파티션 경로
    assert "source" not in row and "origin_country" not in row  # 행 중복·null 패딩 없음

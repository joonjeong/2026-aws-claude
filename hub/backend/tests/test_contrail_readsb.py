"""adsb.lol re-api(readsb v2) 응답 정규화 — 단위 변환, ground 특수값, 건별 격리."""
import pytest

from app.modules.contrail.collector import adsblol_url, box_param
from app.modules.contrail.normalize import normalize_readsb

# readsb v2 필드: hex, flight(콜사인, 후행 공백), lat/lon, alt_baro(ft 또는
# "ground"), gs(knots), track(deg), seen_pos(마지막 위치 후 경과초)
GOOD = {
    "hex": "71bf71", "flight": "KAL123  ", "lat": 37.5, "lon": 127.1,
    "alt_baro": 30000, "gs": 448.1, "track": 88.2, "seen_pos": 10.0,
    "r": "HL7771", "t": "A359",
}
ON_GROUND = {
    "hex": "abc001", "lat": 37.46, "lon": 126.44,
    "alt_baro": "ground", "gs": 5.0, "seen_pos": 2.0,
}
NO_COORDS = {"hex": "dead01", "alt_baro": 12000, "seen_pos": 1.0}


def test_normalize_good_aircraft_converts_units():
    out = normalize_readsb({"ac": [GOOD]}, now=1700000000.0)
    assert len(out) == 1
    f = out[0]
    assert f["id"] == "71bf71"
    assert f["callsign"] == "KAL123"
    assert f["origin_country"] is None          # readsb에는 국가 정보 없음
    assert f["ts"] == 1700000000.0 - 10.0       # now - seen_pos
    assert f["lat"] == 37.5 and f["lon"] == 127.1
    assert f["alt_m"] == pytest.approx(30000 * 0.3048)      # ft → m
    assert f["velocity_ms"] == pytest.approx(448.1 * 0.514444)  # kt → m/s
    assert f["track_deg"] == 88.2
    assert f["on_ground"] is False


def test_ground_special_value():
    f = normalize_readsb({"ac": [ON_GROUND]}, now=100.0)[0]
    assert f["on_ground"] is True
    assert f["alt_m"] is None
    assert f["callsign"] is None                # flight 없음


def test_skips_no_coords_and_malformed_isolated():
    out = normalize_readsb({"ac": [NO_COORDS, "not-a-dict", GOOD]}, now=0.0)
    assert len(out) == 1 and out[0]["id"] == "71bf71"


def test_missing_seen_pos_falls_back_to_now():
    ac = {**GOOD}
    del ac["seen_pos"]
    assert normalize_readsb({"ac": [ac]}, now=42.0)[0]["ts"] == 42.0


def test_missing_track_falls_back_to_calc_track_then_none():
    ac = {**GOOD, "calc_track": 7.0}
    del ac["track"]
    assert normalize_readsb({"ac": [ac]}, now=0.0)[0]["track_deg"] == 7.0
    del ac["calc_track"]
    assert normalize_readsb({"ac": [ac]}, now=0.0)[0]["track_deg"] is None


def test_empty_payload():
    assert normalize_readsb({}, now=0.0) == []
    assert normalize_readsb({"ac": None}, now=0.0) == []


def test_box_param_order_is_latmin_latmax_lonmin_lonmax():
    # OpenSky(lamin,lomin,lamax,lomax)와 순서가 달라 회귀 위험이 큰 지점
    assert box_param((30.0, 120.0, 45.0, 135.0)) == "30.0,45.0,120.0,135.0"


def test_adsblol_url_keeps_raw_commas_and_bare_jv2():
    # re-api는 %2C(콤마 인코딩)와 jv2=(등호 포함) 둘 다 400으로 거부한다 —
    # httpx params 인코딩을 우회해 원시 쿼리로 조립해야 함
    assert (
        adsblol_url("https://re-api.adsb.lol/", (30.0, 120.0, 45.0, 135.0))
        == "https://re-api.adsb.lol/?box=30.0,45.0,120.0,135.0&jv2"
    )

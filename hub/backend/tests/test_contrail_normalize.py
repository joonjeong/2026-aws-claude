"""OpenSky states 배열 정규화 — 인덱스 계약, 좌표 없는 항목 스킵, 건별 격리."""
from app.modules.contrail.normalize import normalize_states

# states 인덱스: 0 icao24, 1 callsign, 2 origin_country, 3 time_position,
# 4 last_contact, 5 lon, 6 lat, 7 baro_altitude, 8 on_ground, 9 velocity,
# 10 true_track, 11.. 미사용
GOOD = ["abc123", "KAL123 ", "Republic of Korea", 1700000000, 1700000001,
        127.1, 37.5, 10058.4, False, 245.8, 88.2, 0, None, None, None, False, 0]
NO_COORDS = ["dead01", None, "France", None, 1700000001,
             None, None, None, True, None, None, 0, None, None, None, False, 0]
MALFORMED = ["short"]


def test_normalize_good_state():
    out = normalize_states({"states": [GOOD]}, now=1700000010.0)
    assert out == [{
        "id": "abc123", "callsign": "KAL123", "origin_country": "Republic of Korea",
        "ts": 1700000000.0, "lon": 127.1, "lat": 37.5, "alt_m": 10058.4,
        "on_ground": False, "velocity_ms": 245.8, "track_deg": 88.2,
        "type": None, "reg": None,  # OpenSky에는 기종·등록부호 없음 — dict 형태 통일
    }]


def test_skips_no_coords_and_malformed_isolated():
    out = normalize_states({"states": [NO_COORDS, MALFORMED, GOOD]}, now=0.0)
    assert len(out) == 1 and out[0]["id"] == "abc123"


def test_ts_falls_back_to_last_contact_then_now():
    s = list(GOOD)
    s[3] = None                      # time_position 없음 → last_contact
    assert normalize_states({"states": [s]}, now=5.0)[0]["ts"] == 1700000001.0
    s[4] = None                      # 둘 다 없음 → now
    assert normalize_states({"states": [s]}, now=5.0)[0]["ts"] == 5.0


def test_empty_payload():
    assert normalize_states({}, now=0.0) == []
    assert normalize_states({"states": None}, now=0.0) == []

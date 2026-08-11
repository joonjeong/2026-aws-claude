"""AISStream 메시지 정규화 — 비정상 입력 격리, 특수값(511/102.3) 처리."""
from app.modules.wake.collector import (
    normalize_position,
    normalize_static,
    ship_type_label,
)

POSITION_MSG = {
    "MessageType": "PositionReport",
    "MetaData": {"MMSI": 440123456, "ShipName": " HANNARA  ", "time_utc": "..."},
    "Message": {"PositionReport": {
        "Latitude": 35.1, "Longitude": 129.0,
        "Sog": 12.3, "Cog": 245.0, "TrueHeading": 244,
    }},
}


def test_normalize_position():
    p = normalize_position(POSITION_MSG, now=1000.0)
    assert p == {
        "id": "440123456", "ts": 1000.0, "lon": 129.0, "lat": 35.1,
        "sog_kn": 12.3, "cog_deg": 245.0, "heading_deg": 244.0,
        "name": "HANNARA",
    }


def test_normalize_position_unavailable_sentinels():
    msg = {
        "MessageType": "PositionReport",
        "MetaData": {"MMSI": 1},
        "Message": {"PositionReport": {
            "Latitude": 0.0, "Longitude": 0.0,
            "Sog": 102.3, "Cog": 360.0, "TrueHeading": 511,
        }},
    }
    p = normalize_position(msg, now=0.0)
    assert p["sog_kn"] is None and p["cog_deg"] is None and p["heading_deg"] is None
    assert p["name"] is None


def test_normalize_position_rejects_missing_fields():
    assert normalize_position({}, now=0.0) is None
    assert normalize_position({"MetaData": {"MMSI": 1}, "Message": {}}, now=0.0) is None


def test_normalize_static_and_type_label():
    msg = {
        "MessageType": "ShipStaticData",
        "MetaData": {"MMSI": 7},
        "Message": {"ShipStaticData": {
            "Name": "EVER GIVEN ", "Type": 71, "CallSign": "ABCD",
        }},
    }
    mmsi, meta = normalize_static(msg)
    assert mmsi == "7"
    assert meta == {"name": "EVER GIVEN", "ship_type": "화물", "callsign": "ABCD"}
    assert normalize_static({}) is None


def test_ship_type_buckets():
    assert ship_type_label(30) == "어선"
    assert ship_type_label(65) == "여객"
    assert ship_type_label(75) == "화물"
    assert ship_type_label(84) == "탱커"
    assert ship_type_label(0) == "기타"
    assert ship_type_label(None) == "기타"

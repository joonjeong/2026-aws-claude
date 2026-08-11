from datalake.sources import aisstream


def _pos_msg(mmsi=440123456, lat=36.0, lon=129.0, sog=12.3, cog=90.0, heading=91):
    return {
        "MessageType": "PositionReport",
        "MetaData": {"MMSI": mmsi, "ShipName": " HANARA "},
        "Message": {"PositionReport": {
            "Latitude": lat, "Longitude": lon,
            "Sog": sog, "Cog": cog, "TrueHeading": heading,
        }},
    }


def test_build_disabled_without_key(monkeypatch):
    monkeypatch.delenv("DATALAKE_AIS_KEY", raising=False)
    assert aisstream.build() is None


def test_subscribe_payload_shape(monkeypatch):
    monkeypatch.setenv("DATALAKE_AIS_KEY", "K")
    src = aisstream.AisStreamClient(api_key="K")
    sub = src.subscribe_payload()
    assert sub == {
        "APIKey": "K",
        "BoundingBoxes": [[[30.0, 120.0], [45.0, 135.0]]],  # kr 프리셋 (hub 기본)
        "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
    }


def test_parse_wraps_raw_message():
    src = aisstream.AisStreamClient(api_key="K")
    (rec,) = src.parse(_pos_msg())
    assert rec.source == "aisstream" and rec.kind == "wake"
    assert rec.payload["MessageType"] == "PositionReport"
    assert rec.meta == {"preset": "kr"}

    assert src.parse("not a dict") == []  # 깨진 메시지 격리


def test_normalize_position_sentinels():
    row = aisstream.normalize_position(
        _pos_msg(sog=102.3, cog=360.0, heading=511), now=1000.0)
    assert row["sog_kn"] is None and row["cog_deg"] is None
    assert row["heading_deg"] is None
    assert row["id"] == "440123456" and row["ts"] == 1000.0
    assert row["name"] == "HANARA"

    ok = aisstream.normalize_position(_pos_msg(), now=1000.0)
    assert ok["sog_kn"] == 12.3 and ok["cog_deg"] == 90.0 and ok["heading_deg"] == 91.0

    assert aisstream.normalize_position({"MetaData": {}}, now=0) is None  # MMSI 없음


def test_normalize_static_and_ship_type():
    msg = {
        "MessageType": "ShipStaticData",
        "MetaData": {"MMSI": 440000001},
        "Message": {"ShipStaticData": {"Name": "EVER X", "Type": 70, "CallSign": "AB1"}},
    }
    mmsi, meta = aisstream.normalize_static(msg)
    assert mmsi == "440000001"
    assert meta == {"name": "EVER X", "ship_type": "화물", "callsign": "AB1"}

    assert aisstream.ship_type_label(30) == "어선"
    assert aisstream.ship_type_label(65) == "여객"
    assert aisstream.ship_type_label(85) == "탱커"
    assert aisstream.ship_type_label("bad") == "기타"

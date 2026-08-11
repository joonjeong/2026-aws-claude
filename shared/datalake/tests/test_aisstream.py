import asyncio
import json

from datalake import aisstream


def _pos_msg(mmsi=440123456, lat=36.0, lon=129.0, sog=12.3, cog=90.0, heading=91):
    return {
        "MessageType": "PositionReport",
        "MetaData": {"MMSI": mmsi, "ShipName": " HANARA "},
        "Message": {"PositionReport": {
            "Latitude": lat, "Longitude": lon,
            "Sog": sog, "Cog": cog, "TrueHeading": heading,
        }},
    }


def test_subscribe_payload_shape():
    assert aisstream.subscribe_payload("K", "kr") == {
        "APIKey": "K",
        "BoundingBoxes": [[[30.0, 120.0], [45.0, 135.0]]],
        "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
    }


def test_position_sentinels_and_static():
    tables = aisstream.to_vessel_and_position(
        _pos_msg(sog=102.3, cog=360.0, heading=511), now=1000.0)
    (pos,) = tables["wake_positions"]
    # 센티널(값 없음)은 키 자체를 생략
    assert "sog_kn" not in pos and "cog_deg" not in pos
    assert "heading_deg" not in pos and pos["mmsi"] == "440123456"
    (vessel,) = tables["wake_vessels"]
    assert vessel["name"] == "HANARA" and "ship_type" not in vessel

    static = aisstream.to_vessel_and_position({
        "MessageType": "ShipStaticData", "MetaData": {"MMSI": 440000001},
        "Message": {"ShipStaticData": {"Name": "EVER X", "Type": 70,
                                       "CallSign": "AB1"}}}, now=1000.0)
    (v,) = static["wake_vessels"]
    assert v == {"mmsi": "440000001", "name": "EVER X", "ship_type": "화물",
                 "callsign": "AB1", "first_seen": 1000.0, "last_seen": 1000.0}
    # (static은 전 필드 값이 있어 생략 없음)

    assert aisstream.to_vessel_and_position({"MetaData": {}}, now=0) == {}


def test_ship_type_label():
    assert [aisstream.ship_type_label(c) for c in (30, 65, 75, 85, "bad")] \
        == ["어선", "여객", "화물", "탱커", "기타"]


class FakeWS:
    def __init__(self, messages):
        self._msgs = list(messages)
        self.sent = []

    async def send(self, data):
        self.sent.append(data)

    async def recv(self):
        if self._msgs:
            return self._msgs.pop(0)
        await asyncio.sleep(3600)  # 접속 유지 — duration 만료까지 대기

    async def close(self):
        pass


async def test_collect_duration_bounded_lands_zones(tmp_path):
    ws = FakeWS([json.dumps(_pos_msg())])

    async def connect(url):
        return ws

    assert await aisstream.collect(tmp_path, "K", "kr", duration_s=0.3,
                                   connect=connect, flush_s=0.05) == 0
    assert json.loads(ws.sent[0])["APIKey"] == "K"  # 구독 프레임 전송

    (landing,) = list(tmp_path.glob("landing/aisstream/wake/dt=*/part-*.jsonl"))
    env = json.loads(landing.read_text())
    assert env["payload"]["MessageType"] == "PositionReport"

    (positions,) = list(tmp_path.glob("bronze/wake_positions/source=*/dt=*/part-*.jsonl"))
    (row,) = [json.loads(x) for x in positions.read_text().splitlines()]
    assert row["mmsi"] == "440123456" and row["sog_kn"] == 12.3

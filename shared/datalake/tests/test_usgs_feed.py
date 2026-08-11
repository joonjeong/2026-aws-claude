import json

import httpx

from datalake import usgs_feed


def _feature(fid="us100", mag=4.5, coords=(127.0, 37.5, 10.0)):
    return {
        "id": fid,
        "properties": {"mag": mag, "place": "Korea", "time": 1786430000000},
        "geometry": {"coordinates": list(coords)},
    }


def test_parse_happy_path():
    rows = usgs_feed.parse({"features": [_feature()]})
    assert rows == [{"id": "us100", "mag": 4.5, "place": "Korea",
                     "time": 1786430000000, "lon": 127.0, "lat": 37.5,
                     "depth_km": 10.0}]


def test_parse_defends_malformed():
    rows = usgs_feed.parse({"features": [
        _feature(),
        {"properties": {}},                       # id 없음 → 필터
        None,                                     # 깨진 feature → 격리
        _feature(fid="us101", mag=float("nan")),  # NaN → 0.0
        {"id": "us102", "properties": {"mag": 3.0, "place": None, "time": "bad"},
         "geometry": {"coordinates": [130.0]}},   # 좌표 패딩·place·time 방어
    ]})
    assert [r["id"] for r in rows] == ["us100", "us101", "us102"]
    assert rows[1]["mag"] == 0.0
    assert rows[2] == {"id": "us102", "mag": 3.0, "place": "unknown", "time": 0,
                       "lon": 130.0, "lat": 0.0, "depth_km": 0.0}


async def test_collect_lands_both_zones(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        assert "earthquake.usgs.gov" in str(request.url)
        return httpx.Response(200, json={"features": [_feature()]})

    assert await usgs_feed.collect(
        tmp_path, transport=httpx.MockTransport(handler)) == 0

    (landing,) = list(tmp_path.glob("landing/usgs_feed/quake/dt=*/part-*.jsonl"))
    env = json.loads(landing.read_text())
    assert env["source"] == "usgs_feed" and env["kind"] == "quake"
    assert env["payload"]["features"][0]["id"] == "us100"  # 원본 그대로
    assert env["meta"]["status"] == 200

    (bronze,) = list(tmp_path.glob("bronze/quake_events/dt=*/part-*.jsonl"))
    (row,) = [json.loads(x) for x in bronze.read_text().splitlines()]
    assert row["id"] == "us100" and row["mag"] == 4.5

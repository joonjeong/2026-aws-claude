import httpx

from datalake.sources import usgs_feed


def _feature(fid="us100", mag=4.5, coords=(127.0, 37.5, 10.0)):
    return {
        "id": fid,
        "properties": {"mag": mag, "place": "Korea", "time": 1786430000000},
        "geometry": {"coordinates": list(coords)},
    }


def test_normalize_happy_path():
    payload = {"features": [_feature()]}
    rows = usgs_feed.normalize(payload)
    assert rows == [{
        "id": "us100", "mag": 4.5, "place": "Korea", "time": 1786430000000,
        "lon": 127.0, "lat": 37.5, "depth_km": 10.0,
    }]


def test_normalize_defends_malformed():
    payload = {"features": [
        _feature(),
        {"properties": {}},          # id 없음 → 스킵
        None,                        # 깨진 feature → 격리
        _feature(fid="us101", mag=float("nan")),  # NaN → 0.0
        {"id": "us102", "properties": {"mag": 3.0, "place": None, "time": "bad"},
         "geometry": {"coordinates": [130.0]}},   # 좌표 패딩·place 없음·time 불량
    ]}
    rows = usgs_feed.normalize(payload)
    assert [r["id"] for r in rows] == ["us100", "us101", "us102"]
    assert rows[1]["mag"] == 0.0
    assert rows[2] == {"id": "us102", "mag": 3.0, "place": "unknown", "time": 0,
                       "lon": 130.0, "lat": 0.0, "depth_km": 0.0}


def test_normalize_empty_payload():
    assert usgs_feed.normalize({}) == []


async def test_fetch_record_envelope():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "earthquake.usgs.gov" in str(request.url)
        return httpx.Response(200, json={"features": [_feature()]})

    client = usgs_feed.UsgsFeedClient(transport=httpx.MockTransport(handler))
    (rec,) = await client.fetch()
    assert rec.source == "usgs_feed"
    assert rec.kind == "quake"
    assert rec.payload["features"][0]["id"] == "us100"
    assert rec.meta["status"] == 200
    assert "url" in rec.meta


def test_build_returns_client():
    client = usgs_feed.build()
    assert client is not None and hasattr(client, "fetch")

import httpx
import pytest

from datalake.sources import contrail


def test_adsblol_url_is_raw_unencoded():
    # re-api는 %2C·jv2= 를 400으로 거부 — 원시 쿼리 형식 고정 (hub와 동일)
    url = contrail.adsblol_url("https://re-api.adsb.lol/", (30.0, 120.0, 45.0, 135.0))
    assert url == "https://re-api.adsb.lol/?box=30.0,45.0,120.0,135.0&jv2"


def test_normalize_readsb_units_and_defense():
    payload = {"ac": [
        {"hex": "abc123", "flight": "KAL123 ", "lat": 37.5, "lon": 127.0,
         "alt_baro": 10000, "gs": 400, "track": 90, "seen_pos": 2.0,
         "t": "B738", "r": "HL1234"},
        {"hex": "def456", "lat": 35.0, "lon": 129.0, "alt_baro": "ground",
         "calc_track": 180},
        {"hex": "nopos1"},                       # 위치 없음 → 스킵
        "junk",                                  # 깨진 항목 → 격리
    ]}
    rows = contrail.normalize(payload, now=1000.0)
    assert len(rows) == 2

    a = rows[0]
    assert a["id"] == "abc123" and a["callsign"] == "KAL123"
    assert a["alt_m"] == pytest.approx(10000 * 0.3048)
    assert a["velocity_ms"] == pytest.approx(400 * 0.514444)
    assert a["ts"] == 998.0  # now - seen_pos
    assert a["on_ground"] is False
    assert a["type"] == "B738" and a["reg"] == "HL1234"

    g = rows[1]
    assert g["on_ground"] is True and g["alt_m"] is None
    assert g["track_deg"] == 180.0  # calc_track 폴백
    assert g["ts"] == 1000.0  # seen_pos 없음 → now


async def test_global_and_region_jobs(monkeypatch):
    monkeypatch.setattr(contrail, "REGION_SPACING_S", 0.0)  # 테스트에선 대기 생략
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        assert request.headers["user-agent"].startswith("DataLake/0.1")
        return httpx.Response(200, json={"ac": [{"hex": "a", "lat": 1, "lon": 2}]})

    src = contrail.ContrailSource(transport=httpx.MockTransport(handler))
    jobs = {j.name: j for j in src.jobs()}
    assert jobs["contrail-global"].interval_s == 600.0  # hub adsblol 기본값
    assert jobs["contrail-regions"].interval_s == 60.0

    (rec,) = await jobs["contrail-global"].fetch()
    assert rec.kind == "global"
    assert "box=-90.0,90.0,-180.0,180.0&jv2" in calls[0]

    recs = await jobs["contrail-regions"].fetch()
    assert [r.kind for r in recs] == [
        "region_kr", "region_japan", "region_europe", "region_us-east"]
    assert all(r.source == "contrail" for r in recs)
    assert recs[0].payload == {"ac": [{"hex": "a", "lat": 1, "lon": 2}]}
    assert recs[0].meta["bbox"] == "30.0,120.0,45.0,135.0"

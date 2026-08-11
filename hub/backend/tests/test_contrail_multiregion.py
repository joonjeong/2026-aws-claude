"""전지구 스냅샷 → 프리셋별 상시 ingest + 아카이브 행 생성 (상시 수집 구조)."""
import time

import pytest

from app.modules.contrail.store import ContrailStore

NOW = time.time()  # stale 프루닝(60분)이 실데이터처럼 동작하도록 현재 시각 기준


def flight(id="f1", lat=37.5, lon=127.1, ts=NOW, **kw):
    base = {
        "id": id, "callsign": "KAL123", "origin_country": None,
        "ts": ts, "lat": lat, "lon": lon, "alt_m": 9000.0,
        "velocity_ms": 230.0, "track_deg": 90.0, "on_ground": False,
        "type": "A359", "reg": "HL7771",
    }
    return {**base, **kw}


@pytest.fixture()
def store():
    return ContrailStore()


def test_ingest_routes_flight_to_matching_preset_only(store):
    # (37.5, 127.1) → kr bbox(30-45, 120-135)만 해당, europe(43-55, -5-20) 아님
    store.ingest_regions([flight()])
    assert [f["id"] for f in store.region("kr").entities()] == ["f1"]
    assert store.region("europe").entities() == []


def test_ingest_overlap_lands_in_both_stores_but_archives_once(store):
    # (35.0, 130.0)은 kr(30-45,120-135)과 japan(30-43,128-146) 겹침 구간
    dims, facts = store.ingest_regions([flight(lat=35.0, lon=130.0)])
    assert [f["id"] for f in store.region("kr").entities()] == ["f1"]
    assert [f["id"] for f in store.region("japan").entities()] == ["f1"]
    assert len(dims) == 1          # dim은 사이클 내 개체당 1행
    assert len(facts) == 1         # fact도 아카이브 게이트로 1행


def test_ingest_outside_all_presets_produces_nothing(store):
    dims, facts = store.ingest_regions([flight(lat=0.0, lon=0.0)])
    assert dims == [] and facts == []
    assert all(store.region(p).entities() == [] for p in store.stores)


def test_fact_rows_respect_archive_gap(store):
    store.ingest_regions([flight(ts=NOW)])
    _, facts_soon = store.ingest_regions([flight(ts=NOW + 10.0, lat=37.6)])
    assert facts_soon == []        # ARCHIVE_GAP_S(300) 이내 재관측은 fact 생략
    _, facts_later = store.ingest_regions([flight(ts=NOW + 400.0, lat=37.7)])
    assert len(facts_later) == 1


def test_region_unknown_preset_raises_keyerror(store):
    with pytest.raises(KeyError):
        store.region("nope")


def test_merge_flights_dedupes_overlap_batches():
    from app.modules.contrail.collector import merge_flights

    a, b = flight(id="a"), flight(id="b")
    merged = merge_flights([[a, b], [b], []])  # kr·japan 겹침 → b 중복 응답
    assert sorted(f["id"] for f in merged) == ["a", "b"]

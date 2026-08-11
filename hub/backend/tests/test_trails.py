"""TrailStore: 다운샘플링·창 프루닝·퇴출 규칙 검증. 시간은 전부 명시 주입."""
from labkit.trails import TrailStore


def _pt(eid="a", ts=0.0, lon=127.0, lat=37.0, **extra):
    return {"id": eid, "ts": ts, "lon": lon, "lat": lat, **extra}


def make_store(**kw):
    defaults = dict(window_s=21_600, gap_s=60, min_move_km=0.5,
                    stale_s=900, max_entities=5)
    defaults.update(kw)
    return TrailStore(**defaults)


def test_first_point_appends_and_latest_merges_extras():
    s = make_store()
    assert s.ingest(_pt(ts=0, sog_kn=10.5)) is True
    assert len(s) == 1
    latest = s.entities()[0]
    assert latest["sog_kn"] == 10.5 and latest["id"] == "a"
    # 단일 점 trail은 trails()에서 제외 (min_points=2)
    assert s.trails() == []


def test_downsample_requires_gap_and_move():
    s = make_store()
    s.ingest(_pt(ts=0))
    # gap 미충족 (59초) — 크게 움직여도 미추가
    assert s.ingest(_pt(ts=59, lon=128.0)) is False
    # gap 충족 + 이동 미충족 (제자리) — 미추가, latest는 갱신됨
    assert s.ingest(_pt(ts=120, lon=127.0, sog_kn=0.1)) is False
    assert s.entities()[0]["sog_kn"] == 0.1
    # gap + 이동(경도 0.1도 ≈ 8.9km) 충족 — 추가
    assert s.ingest(_pt(ts=180, lon=127.1)) is True
    assert s.trails()[0]["points"] == [[0, 127.0, 37.0], [180, 127.1, 37.0]]


def test_window_pruning_drops_old_points():
    s = make_store(window_s=100, gap_s=10, min_move_km=0.0)
    s.ingest(_pt(ts=0))
    s.ingest(_pt(ts=50, lon=127.1))
    s.ingest(_pt(ts=140, lon=127.2))  # cutoff=40 → ts=0 탈락
    pts = s.trails()[0]["points"]
    assert [p[0] for p in pts] == [50, 140]


def test_stale_eviction_and_capacity():
    s = make_store(max_entities=2)
    s.ingest(_pt("a", ts=0))
    s.ingest(_pt("b", ts=100))
    s.prune(now=950)  # a는 950-0 > 900 → 퇴출, b 생존
    assert len(s) == 1
    s.ingest(_pt("c", ts=1000))
    s.ingest(_pt("d", ts=1100))  # 상한 2 초과 → 가장 오래된 b 퇴출
    ids = {e["id"] for e in s.entities()}
    assert ids == {"c", "d"}


def test_merge_meta_only_for_known_entity():
    s = make_store()
    assert s.merge_meta("ghost", {"name": "X"}) is False
    s.ingest(_pt("a", ts=0))
    assert s.merge_meta("a", {"name": "EVER GIVEN"}) is True
    assert s.entities()[0]["name"] == "EVER GIVEN"


def test_reset_empties_everything():
    s = make_store()
    s.ingest(_pt(ts=0))
    s.reset()
    assert len(s) == 0 and s.entities() == []

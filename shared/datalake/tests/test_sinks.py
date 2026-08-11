import json
from datetime import datetime, timezone

from datalake.core.sinks import BronzeSink, LandingSink
from datalake.core.source import Record

TS = datetime(2026, 8, 11, 6, 30, tzinfo=timezone.utc).timestamp()


def _rec(**kw):
    base = dict(
        source="usgs_feed", kind="quake",
        payload={"features": [{
            "id": "us100",
            "properties": {"mag": 4.5, "place": "Korea", "time": 1786430000000},
            "geometry": {"coordinates": [127.0, 37.5, 10.0]},
        }]},
        meta={"url": "u", "status": 200}, fetched_at=TS,
    )
    base.update(kw)
    return Record(**base)


# ── landing: 원본 봉투 ────────────────────────────────────────
def test_landing_envelope_and_append(tmp_path):
    sink = LandingSink(tmp_path)
    sink.write([_rec(), _rec()])

    path = tmp_path / "landing/usgs_feed/quake/dt=2026-08-11/part-06.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2

    env = json.loads(lines[0])
    assert env["fetched_at"] == "2026-08-11T06:30:00Z"
    assert env["source"] == "usgs_feed"
    assert env["kind"] == "quake"
    assert env["payload"]["features"][0]["id"] == "us100"  # 원본 그대로

    sink.write([_rec()])  # 재호출은 append
    assert len(path.read_text(encoding="utf-8").splitlines()) == 3


def test_landing_partition_by_hour_and_source(tmp_path):
    sink = LandingSink(tmp_path)
    ts_next = datetime(2026, 8, 11, 7, 0, tzinfo=timezone.utc).timestamp()
    sink.write([_rec(), _rec(fetched_at=ts_next),
                _rec(source="bbc", kind="news", payload="<rss/>")])

    base = tmp_path / "landing"
    assert (base / "usgs_feed/quake/dt=2026-08-11/part-06.jsonl").exists()
    assert (base / "usgs_feed/quake/dt=2026-08-11/part-07.jsonl").exists()
    assert (base / "bbc/news/dt=2026-08-11/part-06.jsonl").exists()


# ── bronze: 약간의 ETL — 파싱된 테이블 행 ─────────────────────
def test_bronze_writes_parsed_rows(tmp_path):
    BronzeSink(tmp_path).write([_rec()])

    path = tmp_path / "bronze/quake_events/dt=2026-08-11/part-06.jsonl"
    (row,) = [json.loads(x) for x in path.read_text().splitlines()]
    assert row == {"id": "us100", "mag": 4.5, "place": "Korea",
                   "time": 1786430000000, "lon": 127.0, "lat": 37.5,
                   "depth_km": 10.0}


def test_bronze_appends_duplicates(tmp_path):
    # 중복 허용 — dedup은 silver 몫 (메달리온 관행)
    sink = BronzeSink(tmp_path)
    sink.write([_rec()])
    sink.write([_rec()])
    path = tmp_path / "bronze/quake_events/dt=2026-08-11/part-06.jsonl"
    assert len(path.read_text().splitlines()) == 2


def test_bronze_skips_non_contributing_records(tmp_path):
    # contrail_global은 silver 제외 대상 — bronze에도 행을 만들지 않음
    rec = Record(source="adsblol", kind="contrail_global", fetched_at=TS,
                 meta={}, payload={"ac": [{"hex": "a", "lat": 1, "lon": 2}]})
    BronzeSink(tmp_path).write([rec])
    assert not (tmp_path / "bronze").exists()

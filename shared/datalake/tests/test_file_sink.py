import json
from datetime import datetime, timezone

from datalake.core.sinks import FileSink
from datalake.core.source import Record

TS = datetime(2026, 8, 11, 6, 30, tzinfo=timezone.utc).timestamp()


def _rec(**kw):
    base = dict(
        source="quake", kind="usgs_feed", payload={"a": 1},
        meta={"url": "u", "status": 200}, fetched_at=TS,
    )
    base.update(kw)
    return Record(**base)


def test_envelope_and_append(tmp_path):
    sink = FileSink(tmp_path)
    sink.write([_rec(), _rec(payload={"a": 2})])

    path = tmp_path / "bronze/quake/usgs_feed/dt=2026-08-11/part-06.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2

    env = json.loads(lines[0])
    assert env["fetched_at"] == "2026-08-11T06:30:00Z"
    assert env["source"] == "quake"
    assert env["kind"] == "usgs_feed"
    assert env["meta"] == {"url": "u", "status": 200}
    assert env["payload"] == {"a": 1}
    assert json.loads(lines[1])["payload"] == {"a": 2}

    # 재호출은 append
    sink.write([_rec(payload={"a": 3})])
    assert len(path.read_text(encoding="utf-8").splitlines()) == 3


def test_partition_by_hour_and_source(tmp_path):
    sink = FileSink(tmp_path)
    ts_next_hour = datetime(2026, 8, 11, 7, 0, tzinfo=timezone.utc).timestamp()
    sink.write([_rec(), _rec(fetched_at=ts_next_hour), _rec(source="news", kind="bbc")])

    base = tmp_path / "bronze"
    assert (base / "quake/usgs_feed/dt=2026-08-11/part-06.jsonl").exists()
    assert (base / "quake/usgs_feed/dt=2026-08-11/part-07.jsonl").exists()
    assert (base / "news/bbc/dt=2026-08-11/part-06.jsonl").exists()


def test_non_json_serializable_falls_back_to_str(tmp_path):
    sink = FileSink(tmp_path)
    sink.write([_rec(payload={"when": datetime(2026, 8, 11, tzinfo=timezone.utc)})])
    path = tmp_path / "bronze/quake/usgs_feed/dt=2026-08-11/part-06.jsonl"
    env = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(env["payload"]["when"], str)

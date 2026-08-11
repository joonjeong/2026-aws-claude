import gzip
import json
from datetime import date

from datalake.maintenance import compress_old_partitions, prune_old_partitions

TODAY = date(2026, 8, 11)


def _landing_part(root, dt: str, hour="06"):
    d = root / "landing" / "usgs_feed" / "quake" / f"dt={dt}"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"part-{hour}.jsonl"
    path.write_text(json.dumps({"payload": dt}) + "\n", encoding="utf-8")
    return path


def _bronze_part(root, dt: str, hour="06"):
    d = root / "bronze" / "quake_events" / f"dt={dt}"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"part-{hour}.jsonl"
    path.write_text(json.dumps({"id": "x"}) + "\n", encoding="utf-8")
    return path


def test_compress_covers_both_zones_past_only(tmp_path):
    old_landing = _landing_part(tmp_path, "2026-08-10")
    old_bronze = _bronze_part(tmp_path, "2026-08-10")
    today_landing = _landing_part(tmp_path, "2026-08-11")

    n = compress_old_partitions(tmp_path, today=TODAY)
    assert n == 2  # landing + bronze 전일 파티션
    assert not old_landing.exists() and not old_bronze.exists()
    gz = old_landing.with_name("part-06.jsonl.gz")
    with gzip.open(gz, "rt", encoding="utf-8") as f:
        assert json.loads(f.readline())["payload"] == "2026-08-10"
    assert today_landing.exists()  # 오늘 파티션은 건드리지 않음

    assert compress_old_partitions(tmp_path, today=TODAY) == 0  # 멱등


def test_compress_skips_when_gz_exists(tmp_path):
    old = _landing_part(tmp_path, "2026-08-09")
    old.with_name("part-06.jsonl.gz").write_bytes(gzip.compress(b"{}\n"))
    assert compress_old_partitions(tmp_path, today=TODAY) == 0
    assert old.exists()  # 원본 보존 (불완전 gz 덮어쓰기 방지)


def test_prune_old_partitions_both_zones(tmp_path):
    _landing_part(tmp_path, "2026-08-01")   # 10일 전 — 삭제 대상
    _bronze_part(tmp_path, "2026-08-01")
    _landing_part(tmp_path, "2026-08-09")   # 2일 전 — 보존

    assert prune_old_partitions(tmp_path, retention_days=0, today=TODAY) == 0  # 무제한

    n = prune_old_partitions(tmp_path, retention_days=7, today=TODAY)
    assert n == 2
    assert not (tmp_path / "landing/usgs_feed/quake/dt=2026-08-01").exists()
    assert not (tmp_path / "bronze/quake_events/dt=2026-08-01").exists()
    assert (tmp_path / "landing/usgs_feed/quake/dt=2026-08-09").exists()

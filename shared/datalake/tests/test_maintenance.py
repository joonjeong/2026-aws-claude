import gzip
import json
from datetime import date

from datalake.core.maintenance import compress_old_partitions, prune_old_partitions

TODAY = date(2026, 8, 11)


def _make_part(root, dt: str, source="quake", kind="usgs_feed", hour="06"):
    d = root / "raw" / source / kind / f"dt={dt}"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"part-{hour}.jsonl"
    path.write_text(json.dumps({"payload": dt}) + "\n", encoding="utf-8")
    return path


def test_compress_only_past_partitions(tmp_path):
    old = _make_part(tmp_path, "2026-08-10")
    today = _make_part(tmp_path, "2026-08-11")

    n = compress_old_partitions(tmp_path, today=TODAY)
    assert n == 1
    assert not old.exists()
    gz = old.with_name("part-06.jsonl.gz")
    assert gz.exists()
    with gzip.open(gz, "rt", encoding="utf-8") as f:
        assert json.loads(f.readline())["payload"] == "2026-08-10"
    assert today.exists()  # 오늘 파티션은 건드리지 않음

    # 멱등 — 재실행은 아무것도 안 함
    assert compress_old_partitions(tmp_path, today=TODAY) == 0


def test_compress_skips_when_gz_exists(tmp_path):
    old = _make_part(tmp_path, "2026-08-09")
    old.with_name("part-06.jsonl.gz").write_bytes(gzip.compress(b"{}\n"))
    assert compress_old_partitions(tmp_path, today=TODAY) == 0
    assert old.exists()  # 원본 보존 (불완전 gz 덮어쓰기 방지)


def test_prune_old_partitions(tmp_path):
    _make_part(tmp_path, "2026-08-01")   # 10일 전 — 삭제 대상
    _make_part(tmp_path, "2026-08-09")   # 2일 전 — 보존

    assert prune_old_partitions(tmp_path, retention_days=0, today=TODAY) == 0  # 무제한
    assert (tmp_path / "raw/quake/usgs_feed/dt=2026-08-01").exists()

    n = prune_old_partitions(tmp_path, retention_days=7, today=TODAY)
    assert n == 1
    assert not (tmp_path / "raw/quake/usgs_feed/dt=2026-08-01").exists()
    assert (tmp_path / "raw/quake/usgs_feed/dt=2026-08-09").exists()

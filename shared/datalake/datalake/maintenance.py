"""uv run datalake-maintenance — landing·bronze 전일 파티션 gzip + 보존 프루닝.

권장: 일 1회. 압축 DATALAKE_COMPRESS=1(기본), 프루닝
DATALAKE_RAW_RETENTION_DAYS(기본 0 = 무제한). 오늘(UTC) 파티션은 쓰기
중이므로 건드리지 않는다. 멱등.
"""

from __future__ import annotations

import gzip
import logging
import os
import shutil
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Annotated, Optional

import typer

log = logging.getLogger("datalake.maintenance")

ZONES = ("landing", "bronze")
DEFAULT_ROOT = Path(os.environ.get(
    "DATALAKE_ROOT", str(Path(__file__).resolve().parent.parent / "data")))


def _partition_date(dt_dir: Path) -> date | None:
    try:
        return date.fromisoformat(dt_dir.name.removeprefix("dt="))
    except ValueError:
        return None


def _past_partitions(root: Path, today: date) -> list[Path]:
    return sorted(
        p for zone in ZONES for p in (root / zone).glob("**/dt=*/part-*.jsonl")
        if (d := _partition_date(p.parent)) is not None and d < today)


def compress_old_partitions(root: Path, today: date | None = None) -> int:
    """전일 이전 .jsonl → .jsonl.gz 치환. .gz 존재 시 스킵 (보수적)."""
    today = today or datetime.now(timezone.utc).date()
    count = 0
    for path in _past_partitions(root, today):
        gz = path.with_name(path.name + ".gz")
        if gz.exists():
            continue
        with path.open("rb") as src, gzip.open(gz, "wb") as dst:
            shutil.copyfileobj(src, dst)
        path.unlink()
        count += 1
    if count:
        log.info("압축 완료: %d개 파티션 파일", count)
    return count


def prune_old_partitions(root: Path, retention_days: int,
                         today: date | None = None) -> int:
    """보존기간을 넘긴 dt= 디렉토리 삭제. 0 이하 = 무제한 보존 (기본)."""
    if retention_days <= 0:
        return 0
    today = today or datetime.now(timezone.utc).date()
    expired = [d for zone in ZONES for d in (root / zone).glob("**/dt=*")
               if d.is_dir()
               and (pd := _partition_date(d)) is not None
               and (today - pd).days > retention_days]
    for dt_dir in sorted(expired):
        shutil.rmtree(dt_dir)
    if expired:
        log.info("보존기간 프루닝: %d개 파티션 삭제 (%d일 초과)",
                 len(expired), retention_days)
    return len(expired)


def cli(output: Annotated[Optional[Path], typer.Option(
        help="레이크 루트 (기본: env DATALAKE_ROOT)")] = None) -> None:
    """landing·bronze 전일 파티션 gzip + 보존 프루닝."""
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    root = output or DEFAULT_ROOT
    compressed = (compress_old_partitions(root)
                  if os.environ.get("DATALAKE_COMPRESS", "1") == "1" else 0)
    pruned = prune_old_partitions(
        root, int(os.environ.get("DATALAKE_RAW_RETENTION_DAYS", "0")))
    log.info("maintenance 완료: 압축 %d개, 프루닝 %d개 → %s",
             compressed, pruned, root)


def main() -> None:
    typer.run(cli)


if __name__ == "__main__":
    main()

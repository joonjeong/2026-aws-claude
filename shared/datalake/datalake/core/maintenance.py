"""레이크 유지보수 — 전일 파티션 gzip 압축 + 보존기간 프루닝 (일 1회 잡).

contrail 전세계 raw가 지배적(일 300~400MB) — gzip으로 약 1/10 (설계 §5.1).
오늘(UTC) 파티션은 쓰기 중이므로 절대 건드리지 않는다.
"""

from __future__ import annotations

import gzip
import logging
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

log = logging.getLogger("datalake.maintenance")


def _partition_date(dt_dir: Path) -> date | None:
    try:
        return date.fromisoformat(dt_dir.name.removeprefix("dt="))
    except ValueError:
        return None


def compress_old_partitions(root: Path, today: date | None = None) -> int:
    """오늘 이전 파티션의 .jsonl → .jsonl.gz 치환. 압축한 파일 수 반환.

    .gz가 이미 있으면 스킵하고 원본을 남긴다 — 불완전했을 수 있는 기존
    .gz를 덮어쓰지 않는 보수적 선택 (rebuild는 양쪽 다 읽고 싱크가 멱등).
    """
    today = today or datetime.now(timezone.utc).date()
    count = 0
    for path in sorted((root / "raw").glob("*/*/dt=*/part-*.jsonl")):
        d = _partition_date(path.parent)
        if d is None or d >= today:
            continue
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
    count = 0
    for dt_dir in sorted((root / "raw").glob("*/*/dt=*")):
        d = _partition_date(dt_dir)
        if d is None:
            continue
        if (today - d).days > retention_days:
            shutil.rmtree(dt_dir)
            count += 1
    if count:
        log.info("보존기간 프루닝: %d개 파티션 삭제 (%d일 초과)",
                 count, retention_days)
    return count

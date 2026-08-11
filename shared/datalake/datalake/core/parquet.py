"""raw → Parquet 정규화 존 물질화 (파티션 단위 재작성 = 멱등).

<ROOT>/normalized/<table>/dt=YYYY-MM-DD/part-000.parquet
파티션 = 그 날짜(UTC)에 관측된 행. 파티션 내 dedup은 model.TableSpec의
key/merge 규칙, 파티션 간(전역) dedup은 소비 측 몫 (설계 §5.2).
"""

from __future__ import annotations

import gzip
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Iterator

import pyarrow as pa
import pyarrow.parquet as pq

from .. import model
from . import transform
from .source import Record

log = logging.getLogger("datalake.parquet")


def iter_raw(root: Path, date: str | None = None,
             sources: set[str] | None = None) -> Iterator[Record]:
    """raw 존을 시간순 순회하며 Record 재생 (.jsonl / .jsonl.gz).

    date="YYYY-MM-DD"면 해당 dt= 파티션만.
    """
    pattern = f"*/*/dt={date or '*'}/part-*.jsonl*"
    for path in sorted((root / "raw").glob(pattern)):
        source = path.relative_to(root / "raw").parts[0]
        if sources and source not in sources:
            continue
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    env = json.loads(line)
                    fetched = datetime.fromisoformat(
                        env["fetched_at"].replace("Z", "+00:00")).timestamp()
                    yield Record(
                        source=env["source"], kind=env["kind"],
                        payload=env["payload"], meta=env.get("meta") or {},
                        fetched_at=fetched,
                    )
                except Exception:  # 깨진 줄 격리
                    log.warning("skipping bad line in %s", path, exc_info=True)


def _merge(base: dict, new: dict) -> dict:
    """dim류 병합 — 후속 관측의 non-null이 갱신, first/last_seen은 min/max."""
    out = dict(base)
    for k, v in new.items():
        if k == "first_seen":
            out[k] = min(base.get(k) or v, v)
        elif k == "last_seen":
            out[k] = max(base.get(k) or v, v)
        elif v is not None:
            out[k] = v
    return out


def materialize(root: Path, date: str,
                tables: set[str] | None = None) -> dict[str, int]:
    """해당 날짜의 raw → normalized/<table>/dt=<date>/part-000.parquet.

    파티션 파일을 통째로 다시 쓰므로 재실행이 곧 멱등. 테이블별 행 수 반환.
    """
    acc: dict[str, dict[tuple, dict]] = {}
    for rec in iter_raw(Path(root), date=date):
        for table, rows in transform.rows_for(rec).items():
            if tables and table not in tables:
                continue
            spec = model.SPECS[table]
            bucket = acc.setdefault(table, {})
            for row in rows:
                key = tuple(row.get(c) for c in spec.key)
                if key in bucket:
                    if spec.merge:
                        bucket[key] = _merge(bucket[key], row)
                else:
                    bucket[key] = row

    counts: dict[str, int] = {}
    for table, rows_by_key in acc.items():
        spec = model.SPECS[table]
        out_dir = Path(root) / "normalized" / table / f"dt={date}"
        out_dir.mkdir(parents=True, exist_ok=True)
        arrow = pa.Table.from_pylist(list(rows_by_key.values()),
                                     schema=spec.schema)
        pq.write_table(arrow, out_dir / "part-000.parquet",
                       compression="zstd")
        counts[table] = arrow.num_rows
        log.info("normalized %s dt=%s: %d행", table, date, arrow.num_rows)
    return counts

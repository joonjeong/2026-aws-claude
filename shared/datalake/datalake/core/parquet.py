"""bronze → silver 물질화 + landing → bronze 재파생.

silver: bronze(이미 파싱된 행 JSONL)를 읽어 키 dedup·dim 병합 후
<root>/silver/<table>/dt=YYYY-MM-DD/part-000.parquet 재작성 (= 멱등).
XML/CSV 파싱이 없어 가볍고, bronze가 테이블별 경로라 --tables 프루닝이
파일 수준에서 공짜다.

bronze 재파생: ETL 버그 수정 후 landing 원본에서 bronze 파티션을 통째로
다시 만든다 (datalake-bronze).

파티션 = 그 날짜(UTC)에 관측된 행. 파티션 간(전역) dedup은 소비 측 몫.
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


def _iter_jsonl(path: Path) -> Iterator[dict]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
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


def materialize(root: Path | str, date: str,
                tables: set[str] | None = None) -> dict[str, int]:
    """bronze/<table>/dt=<date> → silver/<table>/dt=<date>/part-000.parquet.

    파티션 파일을 통째로 다시 쓰므로 재실행이 곧 멱등. 테이블별 행 수 반환.
    """
    root = Path(root)
    counts: dict[str, int] = {}
    for table, spec in model.SPECS.items():
        if tables and table not in tables:
            continue
        part_dir = root / "bronze" / table / f"dt={date}"
        if not part_dir.exists():
            continue
        rows_by_key: dict[tuple, dict] = {}
        for path in sorted(part_dir.glob("part-*.jsonl*")):
            for row in _iter_jsonl(path):
                key = tuple(row.get(c) for c in spec.key)
                if key in rows_by_key:
                    if spec.merge:
                        rows_by_key[key] = _merge(rows_by_key[key], row)
                else:
                    rows_by_key[key] = row

        out_dir = root / "silver" / table / f"dt={date}"
        out_dir.mkdir(parents=True, exist_ok=True)
        arrow = pa.Table.from_pylist(list(rows_by_key.values()),
                                     schema=spec.schema)
        pq.write_table(arrow, out_dir / "part-000.parquet",
                       compression="zstd")
        counts[table] = arrow.num_rows
        log.info("silver %s dt=%s: %d행", table, date, arrow.num_rows)
    return counts


# ── landing → bronze 재파생 ───────────────────────────────────────────
def iter_landing(root: Path | str, date: str | None = None,
                 sources: set[str] | None = None) -> Iterator[Record]:
    """landing 존을 시간순 순회하며 Record 재생 (.jsonl / .jsonl.gz)."""
    root = Path(root)
    pattern = f"*/*/dt={date or '*'}/part-*.jsonl*"
    for path in sorted((root / "landing").glob(pattern)):
        source = path.relative_to(root / "landing").parts[0]
        if sources and source not in sources:
            continue
        for env in _iter_jsonl(path):
            try:
                fetched = datetime.fromisoformat(
                    env["fetched_at"].replace("Z", "+00:00")).timestamp()
                yield Record(
                    source=env["source"], kind=env["kind"],
                    payload=env["payload"], meta=env.get("meta") or {},
                    fetched_at=fetched,
                )
            except Exception:  # 깨진 봉투 격리
                log.warning("skipping bad envelope in %s", path, exc_info=True)


def rebuild_bronze(root: Path | str, date: str,
                   sources: set[str] | None = None) -> dict[str, int]:
    """landing 원본 → bronze 파티션 통째 재작성 (ETL 수정 후 재파생용).

    해당 날짜의 bronze part 파일들을 지우고 landing에서 다시 만든다.
    테이블별 행 수 반환.
    """
    root = Path(root)
    # 대상 날짜 bronze 파티션 제거 (통째 재작성 = 멱등)
    for part_dir in (root / "bronze").glob(f"*/dt={date}"):
        for f in part_dir.glob("part-*.jsonl*"):
            f.unlink()

    from .sinks import BronzeSink

    sink = BronzeSink(root)
    counts: dict[str, int] = {}
    batch: list[Record] = []
    for rec in iter_landing(root, date=date, sources=sources):
        batch.append(rec)
        if len(batch) >= 200:
            sink.write(batch)
            batch = []
    sink.write(batch)

    for part_dir in (root / "bronze").glob(f"*/dt={date}"):
        n = sum(1 for p in part_dir.glob("part-*.jsonl*")
                for _ in _iter_jsonl(p))
        counts[part_dir.parts[-2]] = n
    return counts

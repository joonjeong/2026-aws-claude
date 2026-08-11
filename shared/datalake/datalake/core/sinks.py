"""싱크 — 수집 명령이 landing(원본)과 bronze(파싱 레코드)를 함께 랜딩한다.

landing: <root>/landing/<source>/<kind>/dt=YYYY-MM-DD/part-HH.jsonl
  한 줄 = 봉투 {"fetched_at","source","kind","meta","payload(원본 그대로)"}
  — 불변 보존, 진실의 원천. ETL 버그 시 datalake-bronze로 재파생.

bronze: <root>/bronze/<table>/dt=YYYY-MM-DD/part-HH.jsonl
  한 줄 = 파싱·타입화된 테이블 행 (transform.rows_for) — 무가공 1:1,
  append-only, 중복 허용 (dedup·병합은 silver 몫 — 메달리온 관행).
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from .source import Record

log = logging.getLogger("datalake.sinks")


def _append_lines(grouped: dict[Path, list[str]]) -> None:
    for path, lines in grouped.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


class LandingSink:
    """원본 봉투를 landing 존에 append."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def _path(self, dt: datetime, r: Record) -> Path:
        return (
            self.root / "landing" / r.source / r.kind
            / f"dt={dt:%Y-%m-%d}" / f"part-{dt:%H}.jsonl"
        )

    def write(self, records: Sequence[Record]) -> None:
        grouped: dict[Path, list[str]] = defaultdict(list)
        for r in records:
            dt = datetime.fromtimestamp(r.fetched_at, tz=timezone.utc)
            line = json.dumps(
                {
                    "fetched_at": dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "source": r.source,
                    "kind": r.kind,
                    "meta": r.meta,
                    "payload": r.payload,
                },
                ensure_ascii=False,
                default=str,
            )
            grouped[self._path(dt, r)].append(line)
        _append_lines(grouped)


class BronzeSink:
    """약간의 ETL — Record를 파싱된 테이블 행으로 변환해 bronze에 append.

    변환은 core/transform.rows_for (각 상류의 normalize 재사용). 수집 명령이
    자기 fetch분만 딱 1회 파싱하므로, 구 normalize의 '그날 전체 재파싱'이
    여기로 분해된다.
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def write(self, records: Sequence[Record]) -> None:
        from . import transform

        grouped: dict[Path, list[str]] = defaultdict(list)
        for r in records:
            dt = datetime.fromtimestamp(r.fetched_at, tz=timezone.utc)
            for table, rows in transform.rows_for(r).items():
                path = (self.root / "bronze" / table
                        / f"dt={dt:%Y-%m-%d}" / f"part-{dt:%H}.jsonl")
                for row in rows:
                    grouped[path].append(
                        json.dumps(row, ensure_ascii=False, default=str))
        _append_lines(grouped)


# 구명 호환 별칭 (테스트·외부 참조용) — landing 존에 쓴다
FileSink = LandingSink

"""싱크 — FileSink가 기본 레이크. 쓰기 실패 처리는 runner의 best-effort 계약 담당.

레이아웃: <root>/bronze/<source>/<kind>/dt=YYYY-MM-DD/part-HH.jsonl (UTC, append-only)
한 줄 = 봉투 {"fetched_at", "source", "kind", "meta", "payload"}.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from .source import Record


class FileSink:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def _path(self, dt: datetime, r: Record) -> Path:
        return (
            self.root / "bronze" / r.source / r.kind
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
        for path, lines in grouped.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")

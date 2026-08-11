"""uv run datalake-bronze — landing 원본 → bronze 재파생 (ETL 수정 후 복구용).

평시에는 불필요 — 수집 명령이 bronze를 직접 랜딩한다. transform/normalize
로직을 고친 뒤 과거 파티션을 새 로직으로 다시 만들 때만 쓴다.
해당 날짜의 bronze 파티션을 통째로 재작성하므로 멱등.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..core.parquet import rebuild_bronze
from . import _common

log = logging.getLogger("datalake.cli")


def main(argv: list[str] | None = None) -> int:
    parser = _common.base_parser("datalake-bronze", __doc__)
    parser.add_argument("--date", default=None,
                        help="대상 파티션 YYYY-MM-DD (기본: 오늘 UTC)")
    parser.add_argument("--sources", default=None,
                        help="쉼표 구분 landing source 선택 (기본: 전체)")
    args = parser.parse_args(argv)
    _common.setup_logging()

    root = _common.resolve_root(args)
    date = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sources = ({s.strip() for s in args.sources.split(",")}
               if args.sources else None)
    counts = rebuild_bronze(root, date, sources=sources)
    total = sum(counts.values())
    log.info("bronze 재파생 완료 dt=%s: %d행 (%s) → %s", date, total,
             ", ".join(f"{t}={n}" for t, n in sorted(counts.items())) or "빈 파티션",
             root)
    return _common.EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())

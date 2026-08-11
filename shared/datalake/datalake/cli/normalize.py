"""uv run datalake-normalize — raw → Parquet 정규화 존 물질화 (멱등).

권장 스케줄: 시간당 1회 (당일 파티션 재작성) + 자정 직후 1회 (전일 확정).
소비: DuckDB·pandas 직독, Postgres는 parquet FDW/pg_duckdb 또는 COPY.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from .. import config, model
from ..core.parquet import materialize
from . import _common

log = logging.getLogger("datalake.cli")


def main(argv: list[str] | None = None) -> int:
    parser = _common.base_parser("datalake-normalize", __doc__)
    parser.add_argument("--date", default=None,
                        help="대상 파티션 YYYY-MM-DD (기본: 오늘 UTC)")
    parser.add_argument("--tables", default=None,
                        help=f"쉼표 구분 선택 (기본 전체: {','.join(model.SPECS)})")
    args = parser.parse_args(argv)
    _common.setup_logging()

    date = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    tables = ({t.strip() for t in args.tables.split(",")}
              if args.tables else None)
    if tables:
        unknown = tables - set(model.SPECS)
        if unknown:
            log.error("알 수 없는 테이블: %s (사용 가능: %s)",
                      sorted(unknown), list(model.SPECS))
            return _common.EXIT_ERROR

    counts = materialize(config.ROOT, date, tables=tables)
    total = sum(counts.values())
    log.info("normalize 완료 dt=%s: %d행 (%s)", date, total,
             ", ".join(f"{t}={n}" for t, n in sorted(counts.items())) or "빈 파티션")
    return _common.EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())

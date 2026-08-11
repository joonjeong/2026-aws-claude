"""uv run datalake-silver — bronze → silver Parquet 물질화 (멱등).

bronze는 이미 파싱된 테이블 행이라 여기서는 키 dedup·dim 병합·컬럼화만
한다 (XML/CSV 파싱 없음 — 얇은 배치). 파티션 통째 재작성 = 재실행 멱등.
소비: DuckDB·pandas 직독, Postgres는 parquet FDW/pg_duckdb 외부 테이블.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from .. import model
from ..core.parquet import materialize
from . import _common

log = logging.getLogger("datalake.cli")


def main(argv: list[str] | None = None) -> int:
    parser = _common.base_parser("datalake-silver", __doc__)
    parser.add_argument("--date", default=None,
                        help="대상 파티션 YYYY-MM-DD (기본: 오늘 UTC)")
    parser.add_argument("--tables", default=None,
                        help=f"쉼표 구분 선택 (기본 전체: {','.join(model.SPECS)})")
    args = parser.parse_args(argv)
    _common.setup_logging()

    root = _common.resolve_root(args)
    date = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    tables = ({t.strip() for t in args.tables.split(",")}
              if args.tables else None)
    if tables:
        unknown = tables - set(model.SPECS)
        if unknown:
            log.error("알 수 없는 테이블: %s (사용 가능: %s)",
                      sorted(unknown), list(model.SPECS))
            return _common.EXIT_ERROR

    counts = materialize(root, date, tables=tables)
    total = sum(counts.values())
    log.info("silver 완료 dt=%s: %d행 (%s) → %s", date, total,
             ", ".join(f"{t}={n}" for t, n in sorted(counts.items())) or "빈 파티션",
             root)
    return _common.EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())

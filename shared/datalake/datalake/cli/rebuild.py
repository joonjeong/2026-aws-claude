"""uv run datalake-rebuild — raw 레이크 → SQLite 파생 존 재구축 (멱등)."""

from __future__ import annotations

import logging

from .. import config
from ..core.sqlite_sink import rebuild
from . import _common

log = logging.getLogger("datalake.cli")


def main(argv: list[str] | None = None) -> int:
    parser = _common.base_parser("datalake-rebuild", __doc__)
    parser.add_argument("--sources", default=None,
                        help="쉼표 구분 소스 선택 (기본: 전체)")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    selected = ({s.strip() for s in args.sources.split(",")}
                if args.sources else None)
    n = rebuild(config.ROOT, config.DB_PATH, sources=selected)
    log.info("rebuild 완료: %d개 레코드 → %s", n, config.DB_PATH)
    return _common.EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())

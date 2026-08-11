"""uv run datalake-maintenance — landing·bronze 전일 파티션 gzip + 보존 프루닝.

권장 스케줄: 일 1회. 압축은 DATALAKE_COMPRESS=1(기본), 프루닝은
DATALAKE_RAW_RETENTION_DAYS(기본 0 = 무제한 보존). 멱등.
"""

from __future__ import annotations

import logging

from .. import config
from ..core.maintenance import compress_old_partitions, prune_old_partitions
from . import _common

log = logging.getLogger("datalake.cli")


def main(argv: list[str] | None = None) -> int:
    parser = _common.base_parser("datalake-maintenance", __doc__)
    args = parser.parse_args(argv)
    _common.setup_logging()
    root = _common.resolve_root(args)
    compressed = (compress_old_partitions(root)
                  if config.COMPRESS_ENABLED else 0)
    pruned = prune_old_partitions(root, config.RAW_RETENTION_DAYS)
    log.info("maintenance 완료: 압축 %d개, 프루닝 %d개", compressed, pruned)
    return _common.EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())

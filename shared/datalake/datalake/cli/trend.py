"""uv run datalake-trend — YouTube 인기 동영상(KR) 1회 수집. 권장 스케줄: 60s.

YT_API_KEY 필요 (hub와 공유 — 합산 쿼터 주의, README 참조).
"""

from __future__ import annotations

import logging

from ..sources import trend
from . import _common

log = logging.getLogger("datalake.cli")


async def _run(args) -> int:
    client = trend.build()
    if client is None:
        logging.basicConfig(level=logging.INFO)
        log.error("trend 비활성: YT_API_KEY 미설정")
        return _common.EXIT_DISABLED
    sinks = _common.build_sinks(args.sqlite)
    try:
        records = await client.fetch()
        _common.report("trend", _common.emit(sinks, records))
    finally:
        _common.close_sinks(sinks)
    return _common.EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = _common.base_parser("datalake-trend", __doc__).parse_args(argv)
    return _common.run_async(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())

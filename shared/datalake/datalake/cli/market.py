"""uv run datalake-market — 미·한 시세 1회 수집. `--extra market` 설치 필요.

권장 스케줄: 장중 45s / 장외 600s (hub 실효 TTL — 비공식 라이브러리
호출량 배려, 케이던스는 오케스트레이터 스케줄로 재현).
"""

from __future__ import annotations

import logging

from ..sources import market
from . import _common

log = logging.getLogger("datalake.cli")


async def _run(args) -> int:
    client = market.build()
    if client is None:
        logging.basicConfig(level=logging.INFO)
        log.error("market 비활성: uv sync --extra market 필요")
        return _common.EXIT_DISABLED
    sinks = _common.build_sinks()
    try:
        kinds = args.kinds.split(",") if args.kinds else None
        records = await client.fetch(kinds)
        _common.report("market", _common.emit(sinks, records))
    finally:
        _common.close_sinks(sinks)
    return _common.EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = _common.base_parser("datalake-market", __doc__)
    parser.add_argument("--kinds", default=None,
                        help=f"쉼표 구분 선택 (기본 전체: {','.join(market.KINDS)})")
    args = parser.parse_args(argv)
    return _common.run_async(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())

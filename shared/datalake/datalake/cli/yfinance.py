"""uv run datalake-yfinance — Yahoo Finance 1회 수집.

생산 kind: market_overview + market_quotes_us (대상: market_symbols.toml).
권장 스케줄: 장중 45s / 장외 600s (비공식 라이브러리 호출량 배려).
"""

from __future__ import annotations

import logging

from ..sources import yfinance
from . import _common

log = logging.getLogger("datalake.cli")


async def _run(args) -> int:
    client = yfinance.build()
    sinks = _common.build_sinks()
    try:
        kinds = args.kinds.split(",") if args.kinds else None
        records = await client.fetch(kinds)
        _common.report("yfinance", _common.emit(sinks, records))
    finally:
        _common.close_sinks(sinks)
    return _common.EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = _common.base_parser("datalake-yfinance", __doc__)
    parser.add_argument("--kinds", default=None,
                        help=f"쉼표 구분 선택 (기본 전체: {','.join(yfinance.KINDS)})")
    args = parser.parse_args(argv)
    return _common.run_async(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())

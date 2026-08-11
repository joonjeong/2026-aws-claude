"""uv run datalake-adsblol — adsb.lol 1회 수집.

한 상류가 여러 데이터셋(kind)을 생산: contrail_global + contrail_region_*.
권장 스케줄: --scope regions 60s / --scope global 600s (hub 기본값).
프리셋 4개는 내부에서 순차 1.1s 간격으로 조회 (re-api 빈도 제한 예의).
"""

from __future__ import annotations

from ..sources import adsblol
from . import _common


async def _run(args) -> int:
    root = _common.resolve_root(args)
    sinks = _common.build_sinks(root)
    client = adsblol.build()
    try:
        records = []
        if args.scope in ("global", "both"):
            records.extend(await client.fetch_global())
        if args.scope in ("regions", "both"):
            records.extend(await client.fetch_regions())
        _common.report("adsblol", _common.emit(sinks, records), root)
    finally:
        _common.close_sinks(sinks)
    return _common.EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = _common.base_parser("datalake-adsblol", __doc__)
    parser.add_argument("--scope", choices=("global", "regions", "both"),
                        default="both", help="수집 범위 (기본: both)")
    args = parser.parse_args(argv)
    return _common.run_async(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())

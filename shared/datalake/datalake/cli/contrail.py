"""uv run datalake-contrail — adsb.lol 항공 트래픽 1회 수집.

권장 스케줄: --scope regions 60s, --scope global 600s (hub 기본값).
프리셋 4개는 내부에서 순차 1.1s 간격으로 조회한다 (re-api 빈도 제한 예의).
"""

from __future__ import annotations


from ..sources import contrail
from . import _common


async def _run(args) -> int:
    sinks = _common.build_sinks(args.sqlite)
    client = contrail.build()
    try:
        records = []
        if args.scope in ("global", "both"):
            records.extend(await client.fetch_global())
        if args.scope in ("regions", "both"):
            records.extend(await client.fetch_regions())
        _common.report("contrail", _common.emit(sinks, records))
    finally:
        _common.close_sinks(sinks)
    return _common.EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = _common.base_parser("datalake-contrail", __doc__)
    parser.add_argument("--scope", choices=("global", "regions", "both"),
                        default="both", help="수집 범위 (기본: both)")
    args = parser.parse_args(argv)
    return _common.run_async(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())

"""uv run datalake-quake — USGS 지진 피드 1회 수집. 권장 스케줄: 60s."""

from __future__ import annotations


from ..sources import quake
from . import _common


async def _run(args) -> int:
    sinks = _common.build_sinks(args.sqlite)
    try:
        records = await quake.build().fetch()
        _common.report("quake", _common.emit(sinks, records))
    finally:
        _common.close_sinks(sinks)
    return _common.EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = _common.base_parser("datalake-quake", __doc__).parse_args(argv)
    return _common.run_async(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())

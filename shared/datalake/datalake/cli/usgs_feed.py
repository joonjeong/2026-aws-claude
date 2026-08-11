"""uv run datalake-usgs-feed — USGS 지진 피드 1회 수집 (kind: quake). 권장 60s."""

from __future__ import annotations

from ..sources import usgs_feed
from . import _common


async def _run(args) -> int:
    root = _common.resolve_root(args)
    sinks = _common.build_sinks(root)
    try:
        records = await usgs_feed.build().fetch()
        _common.report("usgs_feed", _common.emit(sinks, records), root)
    finally:
        _common.close_sinks(sinks)
    return _common.EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = _common.base_parser("datalake-usgs-feed", __doc__).parse_args(argv)
    return _common.run_async(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())

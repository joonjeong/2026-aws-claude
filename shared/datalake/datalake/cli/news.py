"""uv run datalake-news — RSS 15매체 1회 수집. 권장 스케줄: 120s."""

from __future__ import annotations


from ..sources import news
from . import _common


async def _run(args) -> int:
    sinks = _common.build_sinks()
    try:
        feed_ids = args.feeds.split(",") if args.feeds else None
        records = await news.build().fetch(feed_ids)
        _common.report("news", _common.emit(sinks, records))
    finally:
        _common.close_sinks(sinks)
    return _common.EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = _common.base_parser("datalake-news", __doc__)
    parser.add_argument("--feeds", default=None,
                        help="쉼표 구분 매체 id 선택 (기본: 전체 15개)")
    args = parser.parse_args(argv)
    return _common.run_async(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())

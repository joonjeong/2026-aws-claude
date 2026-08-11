"""uv run datalake-rss — RSS 목록 일괄 수집 (kind: news). 권장 120s.

수집 대상은 sources/rss_feeds.toml이 관리 (env DATALAKE_RSS_FEEDS로 교체
가능). 매체 단위 실패 격리 — 한 매체가 죽어도 나머지는 수집된다.
봉투는 매체 단위: source = 매체 id → bronze/<매체>/news/…
"""

from __future__ import annotations

from ..sources import rss
from . import _common


async def _run(args) -> int:
    root = _common.resolve_root(args)
    feed_ids = args.feeds.split(",") if args.feeds else None
    sinks = _common.build_sinks(root)
    try:
        records = await rss.fetch_all(feed_ids)
        _common.report("rss", _common.emit(sinks, records), root)
    finally:
        _common.close_sinks(sinks)
    return _common.EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = _common.base_parser("datalake-rss", __doc__)
    parser.add_argument("--feeds", default=None,
                        help="쉼표 구분 매체 id 선택 (기본: 목록 전체)")
    parser.add_argument("--list", action="store_true", dest="list_feeds",
                        help="수집 대상 목록 출력 후 종료")
    args = parser.parse_args(argv)
    if args.list_feeds:
        for feed_id, feed in rss.FEEDS.items():
            print(f"{feed_id:12s} {feed['lang']:2s}  {feed['name']}  "
                  f"{feed['rss_url']}")
        return _common.EXIT_OK
    return _common.run_async(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())

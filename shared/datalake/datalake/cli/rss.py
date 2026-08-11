"""매체별 RSS 수집 명령 (kind: news). 권장 스케줄: 매체당 120s.

상류 = 매체이므로 명령도 매체별이다: datalake-bbc, datalake-guardian, …
전부 이 모듈의 팩토리로 생성된다 (pyproject [project.scripts]).
"""

from __future__ import annotations

from ..sources import rss
from . import _common


async def _run(feed_id: str) -> int:
    sinks = _common.build_sinks()
    try:
        records = await rss.build(feed_id).fetch()
        _common.report(feed_id, _common.emit(sinks, records))
    finally:
        _common.close_sinks(sinks)
    return _common.EXIT_OK


def _make_main(feed_id: str):
    feed = rss.FEEDS[feed_id]

    def main(argv: list[str] | None = None) -> int:
        _common.base_parser(
            f"datalake-{feed_id}",
            f"uv run datalake-{feed_id} — {feed['name']} RSS 1회 수집",
        ).parse_args(argv)
        return _common.run_async(_run(feed_id))

    return main


main_bbc = _make_main("bbc")
main_guardian = _make_main("guardian")
main_nhk = _make_main("nhk")
main_yna = _make_main("yna")
main_aljazeera = _make_main("aljazeera")
main_hani = _make_main("hani")
main_khan = _make_main("khan")
main_chosun = _make_main("chosun")
main_sbs = _make_main("sbs")
main_mk = _make_main("mk")
main_hankyung = _make_main("hankyung")
main_npr = _make_main("npr")
main_nyt = _make_main("nyt")
main_fox = _make_main("fox")
main_wapo = _make_main("wapo")

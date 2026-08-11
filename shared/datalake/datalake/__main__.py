"""CLI: python -m datalake run [--sources quake,news] [--once]"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from . import config
from .core.runner import Runner
from .core.sinks import FileSink
from .sources import build_sources

log = logging.getLogger("datalake")


def _build_runner(sources_arg: str | None) -> Runner:
    selected = [s.strip() for s in sources_arg.split(",")] if sources_arg else None
    polls, streams = build_sources(selected)
    if not polls and not streams:
        log.warning("활성 소스가 없습니다 (키/엑스트라 확인)")
    sinks: list = [FileSink(config.ROOT)]
    return Runner(polls, streams, sinks, flush_s=config.FLUSH_S)


async def _run(args: argparse.Namespace) -> int:
    runner = _build_runner(args.sources)
    if args.once:
        n = await runner.run_once()
        log.info("run --once 완료: %d개 레코드 → %s", n, config.ROOT)
        return 0
    await runner.start()
    log.info("datalake 기동 — root=%s", config.ROOT)
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        pass
    finally:
        await runner.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="datalake")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run_p = sub.add_parser("run", help="수집 실행")
    run_p.add_argument("--sources", default=None,
                       help="쉼표 구분 소스 선택 (기본: 전체)")
    run_p.add_argument("--once", action="store_true",
                       help="poll 소스 1회 수집 후 종료 (스모크용)")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        log.info("종료")
        return 0


if __name__ == "__main__":
    sys.exit(main())

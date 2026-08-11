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
    if config.SQLITE_ENABLED:
        from .core.sqlite_sink import SqliteSink

        sinks.append(SqliteSink(config.DB_PATH))
        log.info("SQLite 옵션 존 활성: %s", config.DB_PATH)
    polls = [*polls, _MaintenanceSource()]
    return Runner(polls, streams, sinks, flush_s=config.FLUSH_S)


class _MaintenanceSource:
    """일 1회 유지보수 잡 — 전일 파티션 압축 + 보존기간 프루닝."""

    id = "maintenance"

    def jobs(self):
        from .core.maintenance import compress_old_partitions, prune_old_partitions
        from .core.source import Job

        async def tick():
            if config.COMPRESS_ENABLED:
                compress_old_partitions(config.ROOT)
            prune_old_partitions(config.ROOT, config.RAW_RETENTION_DAYS)
            return []

        return [Job("datalake-maintenance", 86_400.0, tick)]


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
    rebuild_p = sub.add_parser(
        "rebuild", help="raw 레이크 → SQLite 재구축 (멱등)")
    rebuild_p.add_argument("--sources", default=None,
                           help="쉼표 구분 소스 선택 (기본: 전체)")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if args.cmd == "rebuild":
        from .core.sqlite_sink import rebuild

        selected = ({s.strip() for s in args.sources.split(",")}
                    if args.sources else None)
        n = rebuild(config.ROOT, config.DB_PATH, sources=selected)
        log.info("rebuild 완료: %d개 레코드 → %s", n, config.DB_PATH)
        return 0
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        log.info("종료")
        return 0


if __name__ == "__main__":
    sys.exit(main())

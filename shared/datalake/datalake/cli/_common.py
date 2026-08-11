"""CLI 공용 — 인자·로깅·싱크 조립·배출. 싱크 실패는 best-effort(로그만).

모든 명령은 --output <root>로 레이크 루트를 지정할 수 있다
(기본: env DATALAKE_ROOT = shared/datalake/data).
수집 명령의 싱크는 landing(원본) + bronze(파싱 레코드) 두 개다.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
from typing import Awaitable, Sequence

from .. import config
from ..core.sinks import BronzeSink, LandingSink
from ..core.source import Record

log = logging.getLogger("datalake.cli")

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_DISABLED = 2  # 키 부재 등으로 상류 비활성 — 스케줄러가 구분할 수 있게


def base_parser(prog: str, description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description=description)
    parser.add_argument(
        "--output", default=None, metavar="ROOT",
        help="레이크 루트 경로 (기본: env DATALAKE_ROOT=shared/datalake/data)",
    )
    return parser


def resolve_root(args) -> Path:
    return Path(args.output) if getattr(args, "output", None) else config.ROOT


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def run_async(coro: Awaitable[int]) -> int:
    """CLI 진입 공용 러너 — 실패는 간결한 에러 로그 + 종료 코드 1.

    재시도·백오프는 넣지 않는다: 외부 스케줄러 소유.
    """
    setup_logging()
    try:
        return asyncio.run(coro)
    except KeyboardInterrupt:
        return EXIT_OK
    except Exception as exc:
        log.error("실패: %s: %s", type(exc).__name__, exc)
        return EXIT_ERROR


def build_sinks(root: Path) -> list:
    # 수집 = landing(원본 봉투) + bronze(약간의 ETL — 파싱 레코드)
    return [LandingSink(root), BronzeSink(root)]


def emit(sinks: Sequence, records: Sequence[Record]) -> int:
    """레코드를 전 싱크에 배출. 싱크 장애가 수집 결과를 못 깨게 격리."""
    if not records:
        return 0
    for sink in sinks:
        try:
            sink.write(records)
        except Exception:
            log.exception("sink %s write failed (%d records)",
                          type(sink).__name__, len(records))
    return len(records)


def close_sinks(sinks: Sequence) -> None:
    for sink in sinks:
        close = getattr(sink, "close", None)
        if close is not None:
            close()


def report(source: str, n: int, root: Path) -> None:
    log.info("[%s] %d개 레코드 → %s", source, n, root)

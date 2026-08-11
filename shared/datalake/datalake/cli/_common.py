"""CLI 공용 — 인자·로깅·싱크 조립·배출. 싱크 실패는 best-effort(로그만)."""

from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Awaitable, Sequence

from .. import config
from ..core.sinks import FileSink
from ..core.source import Record

log = logging.getLogger("datalake.cli")

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_DISABLED = 2  # 키·엑스트라 부재 — 오케스트레이터가 구분할 수 있게


def base_parser(prog: str, description: str) -> argparse.ArgumentParser:
    return argparse.ArgumentParser(prog=prog, description=description)


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def run_async(coro: Awaitable[int]) -> int:
    """CLI 진입 공용 러너 — 실패는 간결한 에러 로그 + 종료 코드 1.

    재시도·백오프는 넣지 않는다: 오케스트레이터(Temporal 예정) 소유.
    """
    setup_logging()
    try:
        return asyncio.run(coro)
    except KeyboardInterrupt:
        return EXIT_OK
    except Exception as exc:
        log.error("실패: %s: %s", type(exc).__name__, exc)
        return EXIT_ERROR


def build_sinks() -> list:
    # 수집은 raw 존에만 쓴다 — 정규화는 datalake-normalize가 배치로 물질화
    return [FileSink(config.ROOT)]


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


def report(source: str, n: int) -> None:
    log.info("[%s] %d개 레코드 → %s", source, n, config.ROOT)

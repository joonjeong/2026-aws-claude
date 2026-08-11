"""uv run datalake-aisstream — AISStream 스트림 구독 수집 (kind: wake).

배치 운영: --duration N 초 동안 구독 후 종료 (겹치지 않게 스케줄).
--duration 0(기본)은 Ctrl-C까지 상시 구독. DATALAKE_AIS_KEY 필요
(hub 키 공유 금지 — 동시 연결 제한).
"""

from __future__ import annotations

import asyncio
import logging
import time

from .. import config
from ..core.stream import StreamCollector
from ..sources import aisstream
from . import _common

log = logging.getLogger("datalake.cli")


async def run_stream(client, sinks, duration_s: float,
                     flush_s: float, connect=None) -> int:
    """구독 → 버퍼 → 주기 플러시. 적재 레코드 수 반환 (테스트용 connect 주입)."""
    buffer: list = []
    collector = StreamCollector(
        "aisstream", client.url,
        on_message=lambda msg: buffer.extend(client.parse(msg)),
        subscribe=client.subscribe_payload,
        connect=connect,
    )
    collector.start()
    total = 0

    def flush() -> None:
        nonlocal total
        if buffer:
            drained, buffer[:] = buffer[:], []
            total += _common.emit(sinks, drained)

    deadline = time.monotonic() + duration_s if duration_s > 0 else None
    try:
        while deadline is None or time.monotonic() < deadline:
            wait = flush_s
            if deadline is not None:
                wait = max(0.05, min(flush_s, deadline - time.monotonic()))
            await asyncio.sleep(wait)
            flush()
    except asyncio.CancelledError:
        pass
    finally:
        collector.stop()
        flush()  # 종료 시 잔여 버퍼 배출
    return total


async def _run(args) -> int:
    client = aisstream.build(preset=args.preset)
    if client is None:
        log.error("aisstream 비활성: DATALAKE_AIS_KEY 미설정 (전용 키 필요)")
        return _common.EXIT_DISABLED
    sinks = _common.build_sinks()
    try:
        n = await run_stream(client, sinks, args.duration, config.FLUSH_S)
        _common.report("aisstream", n)
    finally:
        _common.close_sinks(sinks)
    return _common.EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = _common.base_parser("datalake-aisstream", __doc__)
    parser.add_argument("--duration", type=float, default=0.0,
                        help="구독 유지 시간(초). 0 = Ctrl-C까지 (기본)")
    parser.add_argument("--preset", default=None,
                        choices=sorted(aisstream.PRESETS),
                        help="관심 해역 (기본: env DATALAKE_AISSTREAM_PRESET=kr)")
    args = parser.parse_args(argv)
    return _common.run_async(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())

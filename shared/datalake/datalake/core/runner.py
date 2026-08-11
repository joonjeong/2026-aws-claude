"""소스 → labkit 수집기 조립.

- poll 소스: Job당 PollingCollector 1개 (사이클 실패 격리는 labkit 담당)
- stream 소스: StreamCollector + 내부 버퍼, FLUSH 주기 잡이 드레인
- 싱크 실패는 best-effort: 로그만 남기고 수집을 절대 깨지 않는다 (설계 §5.1)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Sequence

from labkit.poller import PollingCollector
from labkit.stream import StreamCollector

from .source import PollSource, Record, StreamSource

log = logging.getLogger("datalake.runner")


class Runner:
    def __init__(
        self,
        poll_sources: Sequence[PollSource],
        stream_sources: Sequence[StreamSource],
        sinks: Sequence[Any],
        flush_s: float = 10.0,
        connect: Callable[[str], Awaitable[Any]] | None = None,
    ) -> None:
        self._sinks = list(sinks)
        self._jobs = [job for src in poll_sources for job in src.jobs()]
        self._pollers: list[PollingCollector] = [
            PollingCollector(job.name, job.interval_s, job.fetch, on_result=self._emit)
            for job in self._jobs
        ]
        self._streams: list[StreamCollector] = []
        self._buffers: list[list[Record]] = []

        for src in stream_sources:
            buf: list[Record] = []
            self._buffers.append(buf)

            def on_message(msg: dict, _src=src, _buf=buf) -> None:
                _buf.extend(_src.parse(msg))

            payload = src.subscribe_payload()
            self._streams.append(
                StreamCollector(
                    f"{src.id}-stream", src.url, on_message,
                    subscribe=(lambda _p=payload: _p) if payload is not None else None,
                    connect=connect,
                )
            )

        self._flush_poller: PollingCollector | None = None
        if self._streams:
            async def flush_tick() -> None:
                self.flush()

            self._flush_poller = PollingCollector("datalake-flush", flush_s, flush_tick)

    # ── 배출 ──────────────────────────────────────────────
    def _emit(self, records: Sequence[Record] | None) -> None:
        if not records:
            return
        for sink in self._sinks:
            try:
                sink.write(records)
            except Exception:  # best-effort: 싱크 장애가 수집을 못 깨게
                log.exception("sink %s write failed (%d records)",
                              type(sink).__name__, len(records))

    def buffered(self) -> int:
        return sum(len(b) for b in self._buffers)

    def flush(self) -> None:
        for buf in self._buffers:
            if buf:
                drained, buf[:] = buf[:], []
                self._emit(drained)

    # ── 실행 모드 ─────────────────────────────────────────
    async def run_once(self) -> int:
        """모든 poll job을 1회씩 실행 (스트림은 건너뜀). 적재 레코드 수 반환."""
        if self._streams:
            log.info("--once 모드: 스트림 소스 %d개는 건너뜀", len(self._streams))
        total = 0
        for job in self._jobs:
            try:
                records = await job.fetch()
            except Exception as exc:  # 잡 실패 격리 — 폴러 루프와 동일 계약
                log.warning("[%s] fetch failed: %s: %s",
                            job.name, type(exc).__name__, exc)
                continue
            self._emit(records)
            total += len(records or [])
        return total

    async def start(self) -> None:
        for c in (*self._pollers, *self._streams):
            c.start()
        if self._flush_poller is not None:
            self._flush_poller.start()

    async def stop(self) -> None:
        for c in (*self._pollers, *self._streams):
            c.stop()
        if self._flush_poller is not None:
            self._flush_poller.stop()
        self.flush()  # 종료 시 잔여 버퍼 배출

    def status(self) -> dict:
        return {
            "pollers": [p.status for p in self._pollers],
            "streams": [s.status for s in self._streams],
            "buffered": self.buffered(),
        }

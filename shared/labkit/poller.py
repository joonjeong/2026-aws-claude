"""Periodic polling loop with per-cycle failure isolation.

One instance per source: a failing source never blocks its siblings
(each runs in its own asyncio task), and a failing cycle never kills
the loop — the error is recorded in `status` and the next cycle retries.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


class PollingCollector:
    def __init__(
        self,
        name: str,
        interval_s: float,
        fetch: Callable[[], Awaitable[Any]],
        on_result: Callable[[Any], None] | None = None,
    ) -> None:
        self.name = name
        self.interval_s = interval_s
        self._fetch = fetch
        self._on_result = on_result
        self._task: asyncio.Task | None = None
        self.last_success: float | None = None
        self.last_error: str | None = None
        self.cycles = 0
        self.consecutive_failures = 0

    @property
    def status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "last_success": self.last_success,
            "last_error": self.last_error,
            "cycles": self.cycles,
            "consecutive_failures": self.consecutive_failures,
        }

    async def run_once(self) -> None:
        self.cycles += 1
        try:
            result = await self._fetch()
            if self._on_result is not None:
                self._on_result(result)
            self.last_success = time.time()
            self.last_error = None
            self.consecutive_failures = 0
        except Exception as exc:  # cycle isolation: log, record, keep looping
            self.consecutive_failures += 1
            self.last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("[%s] cycle failed: %s", self.name, self.last_error)

    async def _run_forever(self) -> None:
        while True:
            await self.run_once()
            await asyncio.sleep(self.interval_s)

    def start(self) -> asyncio.Task:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(
                self._run_forever(), name=f"poller:{self.name}"
            )
        return self._task

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

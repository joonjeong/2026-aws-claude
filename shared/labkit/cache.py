"""TTL cache with single-flight, and time-bucket helper."""
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable


def time_bucket(seconds: int, now: float | None = None) -> int:
    """Integer bucket index for the current wall clock (e.g. 600 → 10-min)."""
    return int((now if now is not None else time.time()) // seconds)


class TTLCache:
    """get_or_fetch(): expired/missing keys fetch under a per-key lock,
    so concurrent requests for the same key hit upstream exactly once."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[float, Any]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _fresh(self, key: str) -> tuple[bool, Any]:
        entry = self._data.get(key)
        if entry is None:
            return False, None
        expires_at, value = entry
        if time.time() >= expires_at:
            return False, None
        return True, value

    async def get_or_fetch(
        self, key: str, ttl_s: float, fetch: Callable[[], Awaitable[Any]]
    ) -> Any:
        hit, value = self._fresh(key)
        if hit:
            return value
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            hit, value = self._fresh(key)  # someone may have filled it while we waited
            if hit:
                return value
            value = await fetch()
            self._data[key] = (time.time() + ttl_s, value)
            return value

    def invalidate(self, key: str) -> None:
        self._data.pop(key, None)

"""In-memory stores shared by the capstones.

Single asyncio event loop is assumed throughout — no locks.
"""
from __future__ import annotations

from collections import OrderedDict
from typing import Any, Callable


class IdempotentStore:
    """dict keyed by an idempotency key (event id, article link, ...).

    upsert() returns True only on first insertion, so callers can count
    NEW entries per cycle. Over `max_items`, items are evicted in
    ascending `evict_key` order (oldest first when the key is a timestamp).
    """

    def __init__(
        self, max_items: int, evict_key: Callable[[Any], Any] | None = None
    ) -> None:
        self.max_items = max_items
        self._evict_key = evict_key
        self._items: dict[str, Any] = {}

    def upsert(self, key: str, item: Any) -> bool:
        is_new = key not in self._items
        self._items[key] = item
        if is_new and len(self._items) > self.max_items:
            self._evict()
        return is_new

    def _evict(self) -> None:
        overflow = len(self._items) - self.max_items
        if overflow <= 0:
            return
        if self._evict_key is None:
            doomed = list(self._items.keys())[:overflow]
        else:
            ranked = sorted(self._items, key=lambda k: self._evict_key(self._items[k]))
            doomed = ranked[:overflow]
        for key in doomed:
            del self._items[key]

    def get(self, key: str) -> Any | None:
        return self._items.get(key)

    def values(self) -> list[Any]:
        return list(self._items.values())

    def __len__(self) -> int:
        return len(self._items)


class SnapshotRingBuffer:
    """Ring buffer of (bucket, snapshot), idempotent per bucket.

    put() with an existing bucket returns False and stores nothing —
    the in-memory twin of DynamoDB's attribute_not_exists conditional
    write, so a DynamoDB adapter can implement this same interface.
    """

    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self._buf: OrderedDict[int, Any] = OrderedDict()

    def put(self, bucket: int, snapshot: Any) -> bool:
        if bucket in self._buf:
            return False
        self._buf[bucket] = snapshot
        while len(self._buf) > self.capacity:
            self._buf.popitem(last=False)
        return True

    def latest(self) -> tuple[int, Any] | None:
        if not self._buf:
            return None
        bucket = next(reversed(self._buf))
        return bucket, self._buf[bucket]

    def previous(self) -> tuple[int, Any] | None:
        if len(self._buf) < 2:
            return None
        it = reversed(self._buf)
        next(it)
        bucket = next(it)
        return bucket, self._buf[bucket]

    def window(self, n: int) -> list[tuple[int, Any]]:
        return list(self._buf.items())[-n:]

    def all(self) -> list[tuple[int, Any]]:
        return list(self._buf.items())

    def __len__(self) -> int:
        return len(self._buf)

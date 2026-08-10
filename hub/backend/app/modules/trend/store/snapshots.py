"""Snapshot store — thin wrapper over labkit.stores.SnapshotRingBuffer(48).

Interface discipline: only put/latest/previous/window (plus len) are
exposed, so the in-memory ring can later be swapped for the original's
DynamoDB adapter (pk=scope, sk=time bucket, attribute_not_exists write)
without touching callers.

A snapshot is `{"captured_at": iso8601 str, "items": [<=30 normalized items]}`
keyed by an integer time bucket (`labkit.cache.time_bucket(POLL_INTERVAL_S)`).
"""
from __future__ import annotations

from typing import Any

from labkit.stores import SnapshotRingBuffer

from .. import config


class SnapshotStore:
    def __init__(self, capacity: int = config.SNAPSHOT_CAPACITY) -> None:
        self._ring = SnapshotRingBuffer(capacity)

    def put(self, bucket: int, snapshot: dict[str, Any]) -> bool:
        """Idempotent per bucket: returns False (stores nothing) on replay."""
        return self._ring.put(bucket, snapshot)

    def latest(self) -> tuple[int, dict[str, Any]] | None:
        return self._ring.latest()

    def previous(self) -> tuple[int, dict[str, Any]] | None:
        return self._ring.previous()

    def window(self, n: int) -> list[tuple[int, dict[str, Any]]]:
        return self._ring.window(n)

    def __len__(self) -> int:
        return len(self._ring)

"""In-memory quake store: labkit IdempotentStore keyed by USGS event id.

Max 500 items, evicted oldest-first by event time. Tracks per-cycle new
entry ids and the last successful fetch time. Single event loop — no locks.
"""
from __future__ import annotations

import time
from collections import Counter

from labkit import IdempotentStore

from . import config


def top_region(events: list[dict]) -> str | None:
    """Most frequent region: token after the last comma of `place`
    ("10km SW of Adak, Alaska" -> "Alaska"); whole place if no comma."""
    counter: Counter[str] = Counter()
    for e in events:
        place = e.get("place") or "unknown"
        region = place.rsplit(",", 1)[-1].strip() or place
        counter[region] += 1
    if not counter:
        return None
    return counter.most_common(1)[0][0]


class QuakeStore:
    def __init__(self) -> None:
        self._store = IdempotentStore(config.MAX_EVENTS, evict_key=lambda e: e["time"])
        self.last_fetch: float | None = None  # epoch seconds of last successful ingest
        self.last_new_ids: list[str] = []

    def ingest(self, events: list[dict]) -> None:
        self.last_new_ids = [e["id"] for e in events if self._store.upsert(e["id"], e)]
        self.last_fetch = time.time()

    def query(self, hours: float, min_mag: float) -> list[dict]:
        """Events within the time window at/above min_mag, newest first."""
        cutoff_ms = (time.time() - hours * 3600) * 1000
        events = [
            e
            for e in self._store.values()
            if e["time"] >= cutoff_ms and e["mag"] >= min_mag
        ]
        events.sort(key=lambda e: e["time"], reverse=True)
        return events

    def stats(self, events: list[dict]) -> dict:
        return {
            "count": len(events),
            "max_mag": max((e["mag"] for e in events), default=0),
            "top_region": top_region(events),
            "last_fetch": self.last_fetch,
        }

    def __len__(self) -> int:
        return len(self._store)


store = QuakeStore()

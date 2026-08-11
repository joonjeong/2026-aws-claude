"""Per-entity position history for moving objects (ships, aircraft).

quake's IdempotentStore keys point events; TrailStore keys *entities* and
keeps a downsampled trail per entity. A trail point is appended only when
BOTH thresholds pass — gap_s elapsed since the last kept point AND
min_move_km moved — so an anchored ship stays a single point while its
`latest` keeps refreshing. Single asyncio event loop assumed — no locks.
"""
from __future__ import annotations

import math
import time
from collections import deque


def dist_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Equirectangular approximation — plenty for threshold checks."""
    x = math.radians(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    y = math.radians(lat2 - lat1)
    return 6371.0 * math.hypot(x, y)


class TrailStore:
    def __init__(
        self,
        window_s: float = 21_600.0,
        gap_s: float = 60.0,
        min_move_km: float = 0.5,
        stale_s: float = 900.0,
        max_entities: int = 5_000,
    ) -> None:
        self.window_s = window_s
        self.gap_s = gap_s
        self.min_move_km = min_move_km
        self.stale_s = stale_s
        self.max_entities = max_entities
        self._items: dict[str, dict] = {}  # id → {"latest": dict, "trail": deque}
        self.last_ingest: float | None = None  # wall clock of last ingest

    def ingest(self, point: dict) -> bool:
        """Update latest (merge keys); append trail point per downsample rule.
        Returns True iff a trail point was appended (archive gate uses this)."""
        eid = point["id"]
        entry = self._items.get(eid)
        if entry is None:
            entry = self._items[eid] = {"latest": {}, "trail": deque()}
        entry["latest"].update(point)
        if len(self._items) > self.max_entities:
            self._evict_overflow()
        self.last_ingest = time.time()

        trail: deque = entry["trail"]
        added = False
        if not trail:
            trail.append((point["ts"], point["lon"], point["lat"]))
            added = True
        else:
            last_ts, last_lon, last_lat = trail[-1]
            if point["ts"] - last_ts >= self.gap_s and (
                dist_km(last_lon, last_lat, point["lon"], point["lat"])
                >= self.min_move_km
            ):
                trail.append((point["ts"], point["lon"], point["lat"]))
                added = True
        cutoff = point["ts"] - self.window_s
        while trail and trail[0][0] < cutoff:
            trail.popleft()
        return added

    def merge_meta(self, eid: str, meta: dict) -> bool:
        """Merge slow-changing metadata (ship name/type). Unknown id → False."""
        entry = self._items.get(eid)
        if entry is None:
            return False
        entry["latest"].update(meta)
        return True

    def entities(self) -> list[dict]:
        return [e["latest"] for e in self._items.values()]

    def trails(self, min_points: int = 2) -> list[dict]:
        return [
            {"id": eid, "points": [list(p) for p in e["trail"]]}
            for eid, e in self._items.items()
            if len(e["trail"]) >= min_points
        ]

    def prune(self, now: float | None = None) -> None:
        """Evict entities unobserved for stale_s (by their last point ts)."""
        now = time.time() if now is None else now
        doomed = [
            eid
            for eid, e in self._items.items()
            if now - e["latest"]["ts"] > self.stale_s
        ]
        for eid in doomed:
            del self._items[eid]

    def _evict_overflow(self) -> None:
        overflow = len(self._items) - self.max_entities
        if overflow <= 0:
            return
        ranked = sorted(self._items, key=lambda k: self._items[k]["latest"]["ts"])
        for eid in ranked[:overflow]:
            del self._items[eid]

    def reset(self) -> None:
        self._items.clear()

    def __len__(self) -> int:
        return len(self._items)

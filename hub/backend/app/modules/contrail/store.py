"""Contrail store: 전 세계 최신 스냅샷 + 관심지역 TrailStore + 아카이브 게이트."""
from __future__ import annotations

import time

from labkit import TrailStore

from . import config


class ContrailStore:
    def __init__(self) -> None:
        self.trails = TrailStore(
            window_s=config.TRAIL_WINDOW_S,
            gap_s=config.TRAIL_GAP_S,
            min_move_km=config.TRAIL_MIN_MOVE_KM,
            stale_s=config.STALE_S,
            max_entities=config.MAX_ENTITIES,
        )
        self.active_preset = config.DEFAULT_PRESET
        self.global_flights: list[dict] = []
        self.global_fetch: float | None = None
        self._last_archived: dict[str, float] = {}
        self.last_preset_switch: float | None = None

    def preset(self) -> dict:
        return next(p for p in config.PRESETS if p["id"] == self.active_preset)

    def set_global(self, flights: list[dict]) -> None:
        self.global_flights = flights
        self.global_fetch = time.time()

    def should_archive(self, eid: str, ts: float) -> bool:
        last = self._last_archived.get(eid)
        if last is not None and ts - last < config.ARCHIVE_GAP_S:
            return False
        self._last_archived[eid] = ts
        if len(self._last_archived) > config.MAX_ENTITIES * 2:
            self._last_archived.clear()
        return True

    def reset(self) -> None:
        """프리셋 전환: 지역 trail만 리셋 (전 세계 스냅샷은 무관)."""
        self.trails.reset()
        self._last_archived.clear()


store = ContrailStore()

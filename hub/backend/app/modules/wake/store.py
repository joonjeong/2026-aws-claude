"""Wake store: labkit TrailStore + 활성 프리셋 + 아카이브 게이트."""
from __future__ import annotations

from labkit import TrailStore

from . import config


class WakeStore:
    def __init__(self) -> None:
        self.trails = TrailStore(
            window_s=config.TRAIL_WINDOW_S,
            gap_s=config.TRAIL_GAP_S,
            min_move_km=config.TRAIL_MIN_MOVE_KM,
            stale_s=config.STALE_S,
            max_entities=config.MAX_ENTITIES,
        )
        self.active_preset = config.DEFAULT_PRESET
        self._last_archived: dict[str, float] = {}
        self.last_preset_switch: float | None = None

    def preset(self) -> dict:
        return next(p for p in config.PRESETS if p["id"] == self.active_preset)

    def should_archive(self, eid: str, ts: float) -> bool:
        """fact 기록 게이트: 개체당 ARCHIVE_GAP_S 간격."""
        last = self._last_archived.get(eid)
        if last is not None and ts - last < config.ARCHIVE_GAP_S:
            return False
        self._last_archived[eid] = ts
        if len(self._last_archived) > config.MAX_ENTITIES * 2:  # 게이트 dict 상한
            self._last_archived.clear()
        return True

    def reset(self) -> None:
        """프리셋 전환: trail·게이트 전부 리셋 (아카이브 이력은 유지)."""
        self.trails.reset()
        self._last_archived.clear()


store = WakeStore()

"""Contrail store: 전 세계 최신 스냅샷 + 프리셋별 상시 TrailStore + 아카이브 게이트.

전지구 60초 스냅샷 하나에서 모든 프리셋 지역을 파생한다(상시 수집 구조,
2026-08-11). 프리셋 전환은 서버 상태 변경 없이 조회 대상만 바뀐다.
"""
from __future__ import annotations

import time

from labkit import TrailStore

from . import config


def _in_bbox(lat: float, lon: float, bbox: tuple) -> bool:
    lat_min, lon_min, lat_max, lon_max = bbox
    return lat_min <= lat <= lat_max and lon_min <= lon <= lon_max


class ContrailStore:
    def __init__(self) -> None:
        self.stores: dict[str, TrailStore] = {
            p["id"]: TrailStore(
                window_s=config.TRAIL_WINDOW_S,
                gap_s=config.TRAIL_GAP_S,
                min_move_km=config.TRAIL_MIN_MOVE_KM,
                stale_s=config.STALE_S,
                max_entities=config.MAX_ENTITIES,
            )
            for p in config.PRESETS
        }
        self.global_flights: list[dict] = []
        self.global_fetch: float | None = None
        self._last_archived: dict[str, float] = {}

    def preset(self, preset_id: str) -> dict:
        p = next((p for p in config.PRESETS if p["id"] == preset_id), None)
        if p is None:
            raise KeyError(preset_id)
        return p

    def region(self, preset_id: str) -> TrailStore:
        return self.stores[preset_id]

    def set_global(self, flights: list[dict]) -> None:
        self.global_flights = flights
        self.global_fetch = time.time()

    def ingest_regions(self, flights: list[dict]) -> tuple[list[tuple], list[tuple]]:
        """스냅샷을 모든 프리셋 스토어에 반영하고 (dim, fact) 행 배치를 돌려준다.

        겹치는 프리셋(kr·japan 등)에 동시에 속한 개체도 dim은 사이클당 1행,
        fact는 개체당 ARCHIVE_GAP_S 게이트로 1행만 나간다.
        """
        dims: list[tuple] = []
        facts: list[tuple] = []
        seen: set[str] = set()
        for p in config.PRESETS:
            trail_store = self.stores[p["id"]]
            for f in flights:
                if not _in_bbox(f["lat"], f["lon"], p["bbox"]):
                    continue
                added = trail_store.ingest(f)
                if not added or f["id"] in seen:
                    continue
                seen.add(f["id"])
                dims.append((
                    f["id"], f["callsign"], f["origin_country"], f["ts"], f["ts"],
                ))
                if self.should_archive(f["id"], f["ts"]):
                    facts.append((
                        f["id"], f["ts"], f["lon"], f["lat"], f["alt_m"],
                        f["velocity_ms"], f["track_deg"], int(f["on_ground"]),
                    ))
            trail_store.prune()
        return dims, facts

    def should_archive(self, eid: str, ts: float) -> bool:
        last = self._last_archived.get(eid)
        if last is not None and ts - last < config.ARCHIVE_GAP_S:
            return False
        self._last_archived[eid] = ts
        if len(self._last_archived) > config.MAX_ENTITIES * 2:
            self._last_archived.clear()
        return True


store = ContrailStore()

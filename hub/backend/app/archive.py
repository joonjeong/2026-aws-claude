"""횡단 아카이브 조립 지점 — labkit.Archive 인스턴스 + best-effort 헬퍼.

모듈은 반드시 이 헬퍼를 통해 기록한다: 아카이브 실패는 로그만 남기고
폴러 사이클·API 응답을 절대 깨지 않는다 (설계 2026-08-11).
"""
from __future__ import annotations

import logging
from pathlib import Path

from labkit import Archive, PollingCollector
from labkit.config import env_int, env_str

log = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parent.parent  # hub/backend
DB_PATH = env_str("LAB_DB_PATH", str(_BACKEND_DIR / "data" / "lab.db"))
RETENTION_DAYS = env_int("LAB_ARCHIVE_RETENTION_DAYS", 30)

archive = Archive(DB_PATH)


def archive_entities(module: str, items: list[tuple[str, dict]]) -> None:
    try:
        archive.put_entities(module, items)
    except Exception:  # noqa: BLE001 — best-effort: 수집 경로를 깨지 않는다
        log.exception("archive entities failed (module=%s)", module)


def archive_snapshot(module: str, kind: str, payload: object) -> None:
    try:
        archive.put_snapshot(module, kind, payload)
    except Exception:  # noqa: BLE001 — best-effort
        log.exception("archive snapshot failed (module=%s kind=%s)", module, kind)


def archive_counts() -> dict[str, int]:
    try:
        return archive.counts()
    except Exception:  # noqa: BLE001 — healthz는 아카이브 장애에도 응답해야 함
        log.exception("archive counts failed")
        return {}


async def _prune_tick() -> int:
    deleted = archive.prune_snapshots(RETENTION_DAYS)
    if deleted:
        log.info("archive pruned %d snapshot rows (>%dd)", deleted, RETENTION_DAYS)
    return deleted


# 기동 직후 첫 틱이 1회 프루닝, 이후 24시간 간격 (main.py lifespan이 start/stop)
prune_poller = PollingCollector("archive-prune", 86_400, _prune_tick)

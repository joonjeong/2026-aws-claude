"""entities JSON → quake_events 멱등 백필 (startup에서 매번 호출, 빈 상태면 no-op).

비정상 행(JSON 파싱·키 누락)은 경고 로그 후 스킵하고 entities에 남긴다 —
원본이 유일한 사본이므로 삭제하지 않는다 (스펙 확정 결정).
"""
from __future__ import annotations

import json
import logging

from ...archive import archive_insert, archive_query
from . import schema

logger = logging.getLogger(__name__)


def migrate_entities() -> int:
    """파싱에 성공해 INSERT 배치에 포함된 건수를 반환. best-effort."""
    rows = archive_query(
        "SELECT id, payload FROM entities WHERE module = 'quake'"
    )
    if not rows:
        return 0
    events: list[tuple] = []
    for eid, payload in rows:
        try:
            e = json.loads(payload)
            events.append((
                str(eid), float(e["mag"]), str(e["place"]), int(e["time"]),
                float(e["lon"]), float(e["lat"]), float(e["depth_km"]),
            ))
        except Exception:  # 한 행의 비정상이 나머지를 막지 않는다
            logger.warning(
                "quake migrate: skipping malformed entities row %r",
                eid, exc_info=True,
            )
    inserted = archive_insert(schema.INSERT_EVENT, events)
    deleted = archive_insert(schema.DELETE_MIGRATED, [()])  # 인자 없는 단일 실행
    logger.info(
        "quake migrate: %d parsed, %d inserted, %d entities rows deleted",
        len(events), inserted, deleted,
    )
    return len(events)

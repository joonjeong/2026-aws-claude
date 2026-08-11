"""snapshots JSON → trend_videos/trend_video_stats 멱등 백필 (startup마다, 비면 no-op).

스냅샷은 자연키가 없어 rowid로 정확히 읽은 행만 지운다. 삭제 전에 해당 버킷의
fact 행 존재를 검증(quake 패턴) — 비정상 스냅샷(키 누락·파싱 실패)은 경고 후
스킵하고 남긴다 (30일 보존으로 자연 소멸).
"""
from __future__ import annotations

import json
import logging

from ...archive import archive_execute, archive_insert, archive_query
from . import schema
from .collector.youtube import trending_rows

logger = logging.getLogger(__name__)


def migrate_snapshots() -> int:
    """이관을 마쳐 snapshots에서 삭제한 스냅샷 수를 반환. best-effort."""
    rows = archive_query(
        "SELECT rowid, payload FROM snapshots"
        " WHERE module = 'trend' AND kind = 'trending'"
    )
    if not rows:
        return 0
    deletable: list[int] = []
    for rowid, payload in rows:
        try:
            snap = json.loads(payload)
            ts, dims, facts = trending_rows(int(snap["bucket"]), snap)
        except Exception:  # 한 스냅샷의 비정상이 나머지를 막지 않는다
            logger.warning(
                "trend migrate: skipping malformed snapshot rowid=%r",
                rowid, exc_info=True,
            )
            continue
        archive_insert(schema.UPSERT_VIDEO, dims)
        archive_insert(schema.INSERT_STAT, facts)
        if not facts:
            deletable.append(rowid)  # 빈 스냅샷: 옮길 것이 없음
            continue
        (n,) = archive_query(
            "SELECT COUNT(*) FROM trend_video_stats WHERE ts = ?", (ts,)
        )[0]
        if n >= len(facts):  # 존재검증 — insert rowcount로 성공 판정 금지
            deletable.append(rowid)
    if deletable:
        marks = ",".join("?" * len(deletable))
        archive_execute(
            f"DELETE FROM snapshots WHERE rowid IN ({marks})",  # noqa: S608
            tuple(deletable),
        )
    logger.info(
        "trend migrate: %d snapshots read, %d migrated+deleted",
        len(rows), len(deletable),
    )
    return len(deletable)

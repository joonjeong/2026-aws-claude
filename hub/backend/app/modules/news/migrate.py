"""entities JSON → news_articles 멱등 백필 (startup에서 매번 호출, 비면 no-op).

비정상 행(JSON 파싱·키 누락)은 경고 로그 후 스킵하고 entities에 남긴다 —
원본이 유일한 사본이므로 삭제하지 않는다 (quake 백필과 동일 결정).
"""
from __future__ import annotations

import json
import logging

from ...archive import archive_execute, archive_insert, archive_query
from . import schema

logger = logging.getLogger(__name__)


def migrate_entities() -> int:
    """파싱에 성공해 INSERT 배치에 포함된 건수를 반환. best-effort."""
    rows = archive_query(
        "SELECT id, first_seen, payload FROM entities WHERE module = 'news'"
    )
    if not rows:
        return 0
    articles: list[tuple] = []
    for link, first_seen, payload in rows:
        try:
            a = json.loads(payload)
            articles.append((
                str(link), str(a["source"]), str(a["title"]),
                a.get("published"), a.get("summary"), float(first_seen),
            ))
        except Exception:  # 한 행의 비정상이 나머지를 막지 않는다
            logger.warning(
                "news migrate: skipping malformed entities row %r",
                link, exc_info=True,
            )
    inserted = archive_insert(schema.INSERT_ARTICLE, articles)
    deleted = archive_execute(schema.DELETE_MIGRATED)
    logger.info(
        "news migrate: %d parsed, %d inserted, %d entities rows deleted",
        len(articles), inserted, deleted,
    )
    return len(articles)

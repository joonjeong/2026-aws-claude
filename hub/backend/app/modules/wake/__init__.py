"""Wake Watch — 관심 해역 선박 항적 모니터 (AISStream WebSocket).

Hub module contract: META, router, startup(), shutdown(), health().
"""
import logging

from ...archive import archive_ensure_schema, register_prune
from . import config, schema
from .api import health, router
from .collector import collector

logger = logging.getLogger(__name__)

META = {
    "id": "wake",
    "title": "Wake Watch",
    "tagline": "관심 해역 선박 항적 — AIS 실시간 스트림",
    "icon": "🌊",
}

__all__ = ["META", "router", "startup", "shutdown", "health"]


async def startup() -> None:
    archive_ensure_schema("wake", schema.DDL, schema.TABLES)
    register_prune("wake_positions", "ts", config.POSITIONS_RETENTION_DAYS)
    if config.AIS_KEY:
        collector.start()
    else:
        logger.warning("wake: WAKE_AIS_KEY 미설정 — 수집기 비활성 (health=no_key)")


async def shutdown() -> None:
    collector.stop()

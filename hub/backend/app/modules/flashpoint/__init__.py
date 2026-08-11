"""Flashpoint Watch — GDELT 분쟁·불안 이벤트 모니터 (15분 배치).

Hub module contract: META, router, startup(), shutdown(), health().
"""
from ...archive import archive_ensure_schema, register_prune
from . import config, schema
from .api import health, router
from .collector import collector

META = {
    "id": "flashpoint",
    "title": "Flashpoint Watch",
    "tagline": "전 세계 분쟁·불안 이벤트 — GDELT 뉴스 보도 기반",
    "icon": "⚡",
}

__all__ = ["META", "router", "startup", "shutdown", "health"]


async def startup() -> None:
    archive_ensure_schema("flashpoint", schema.DDL, schema.TABLES)
    register_prune("flashpoint_events", "ts", config.RETENTION_DAYS)
    collector.start()


async def shutdown() -> None:
    collector.stop()

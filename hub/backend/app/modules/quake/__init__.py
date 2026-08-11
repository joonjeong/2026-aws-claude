"""Quake Watch — worldwide earthquake monitor (USGS 2.5+ day feed).

Hub module contract: META, router, startup(), shutdown(), health().
"""
from ...archive import archive_ensure_schema
from . import schema
from .api import health, router
from .collector import collector
from .migrate import migrate_entities

META = {
    "id": "quake",
    "title": "Quake Watch",
    "tagline": "전 세계 실시간 지진 모니터 — USGS 60초 수집",
    "icon": "🌋",
}

__all__ = ["META", "router", "startup", "shutdown", "health"]


async def startup() -> None:
    archive_ensure_schema("quake", schema.DDL, schema.TABLES)
    migrate_entities()  # entities 잔여분 멱등 백필 (비면 no-op)
    collector.start()


async def shutdown() -> None:
    collector.stop()

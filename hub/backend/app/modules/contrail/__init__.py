"""Contrail Watch — 전 세계 항공 트래픽 + 관심지역 항적 (OpenSky ADS-B).

Hub module contract: META, router, startup(), shutdown(), health().
"""
from ...archive import archive_ensure_schema, register_prune
from . import config, schema
from .api import health, router
from .collector import global_collector, region_collector

META = {
    "id": "contrail",
    "title": "Contrail Watch",
    "tagline": "전 세계 항공 트래픽·관심지역 항적 — OpenSky",
    "icon": "✈️",
}

__all__ = ["META", "router", "startup", "shutdown", "health"]


async def startup() -> None:
    archive_ensure_schema("contrail", schema.DDL, schema.TABLES)
    register_prune("contrail_positions", "ts", config.POSITIONS_RETENTION_DAYS)
    global_collector.start()
    region_collector.start()


async def shutdown() -> None:
    global_collector.stop()
    region_collector.stop()

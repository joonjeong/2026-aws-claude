"""Quake Watch — worldwide earthquake monitor (USGS 2.5+ day feed).

Hub module contract: META, router, startup(), shutdown(), health().
"""
from .api import health, router
from .collector import collector

META = {
    "id": "quake",
    "title": "Quake Watch",
    "tagline": "전 세계 실시간 지진 모니터 — USGS 60초 수집",
    "icon": "🌋",
}

__all__ = ["META", "router", "startup", "shutdown", "health"]


async def startup() -> None:
    collector.start()


async def shutdown() -> None:
    collector.stop()

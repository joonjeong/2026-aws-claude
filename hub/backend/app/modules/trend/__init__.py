"""Trend Radar module — YouTube 급상승 수집/분석 (hub module contract).

Absorbs the old standalone main.py: the lifespan poller becomes
startup()/shutdown(), static serving is the hub's job, and the router
exposes relative paths that the hub mounts under /api/trend.

Env: YT_API_KEY (live), YT_FIXTURE (fixture snapshots for key-less
verification), AWS_BEARER_TOKEN_BEDROCK (briefing), POLL_INTERVAL_S.
"""
from __future__ import annotations

from typing import Any

from ...archive import archive_ensure_schema, register_prune
from . import config, schema, state
from .api.routes import router  # noqa: F401  (hub contract: router)
from .collector import youtube as collector_mod
from .migrate import migrate_snapshots

META = {
    "id": "trend",
    "title": "Trend Radar",
    "tagline": "유튜브 급상승 30 — rank delta·NEW·카테고리 점유율·AI 브리핑",
    "icon": "📈",
}


async def startup() -> None:
    """videoCategories(hl=ko) once (failure -> default names), then start
    the PollingCollector that feeds the snapshot ring buffer."""
    archive_ensure_schema("trend", schema.DDL, schema.TABLES)
    register_prune("trend_video_stats", "ts", config.STATS_RETENTION_DAYS)
    migrate_snapshots()  # snapshots 잔여분 멱등 백필 (비면 no-op)
    await collector_mod.load_category_names()
    state.collector = collector_mod.create_collector(state.store)
    state.collector.start()


async def shutdown() -> None:
    if state.collector is not None:
        state.collector.stop()
        state.collector = None


def health() -> dict[str, Any]:
    if state.collector is None:
        collector_status = {"name": "youtube-trending", "last_success": None,
                            "last_error": "not started", "cycles": 0,
                            "consecutive_failures": 0}
    else:
        collector_status = state.collector.status
    return {"collector": collector_status, "snapshots": len(state.store)}

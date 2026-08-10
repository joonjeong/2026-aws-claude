"""News module runtime: ArticleStore + one PollingCollector per source + Lens.

Absorbs the old newsroom main.py lifespan logic (hub design §7): objects are
created at import time; the hub lifespan drives start()/stop() through the
module's startup()/shutdown(). One PollingCollector per RSS source (4 × 120s)
keeps the per-source failure isolation — a failing feed only fails its own task.
"""
from __future__ import annotations

import asyncio

from labkit import PollingCollector

from ...archive import archive_entities
from . import config
from .collector.rss import fetch_articles
from .llm.lens import Lens
from .store.articles import ArticleStore


def _make_collector(source: dict, store: ArticleStore) -> PollingCollector:
    async def fetch() -> list[dict]:
        return await fetch_articles(source)

    def on_result(articles: list[dict]) -> None:
        store.ingest(source["id"], articles)
        # 이력 아카이브 (best-effort) — link PK, 기사 dict에 source 포함됨
        archive_entities("news", [(a["link"], a) for a in articles])

    return PollingCollector(
        name=source["id"],
        interval_s=config.POLL_INTERVAL_S,
        fetch=fetch,
        on_result=on_result,
    )


store = ArticleStore()
collectors: dict[str, PollingCollector] = {
    s["id"]: _make_collector(s, store) for s in config.SOURCES
}
lens = Lens(store)
_tasks: list = []


async def start() -> None:
    _tasks[:] = [c.start() for c in collectors.values()]  # one task per source


async def stop() -> None:
    for collector in collectors.values():
        collector.stop()
    await asyncio.gather(*_tasks, return_exceptions=True)
    _tasks.clear()


def health() -> dict:
    """Module status for the hub /healthz aggregate and launcher card."""
    return {
        "status": "ok",
        "articles": store.total(),
        "sources": {
            sid: {
                "last_success": collector.status["last_success"],
                "last_error": collector.status["last_error"],
                "count": store.count(sid),
            }
            for sid, collector in collectors.items()
        },
    }

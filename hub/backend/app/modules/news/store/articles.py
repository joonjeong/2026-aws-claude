"""Per-source article stores: labkit.IdempotentStore(50), keyed by link.

Idempotency contract (docs/newsroom.md #4): the article link is the key;
when the same article re-appears, only `published` is refreshed. Eviction
is by oldest `published` first (evict_key), max 50 per source.
Article records hold headline+summary+link only — never full text.
"""
from __future__ import annotations

from labkit import IdempotentStore

from .. import config


class ArticleStore:
    def __init__(self, sources: list[dict] | None = None) -> None:
        sources = sources if sources is not None else config.SOURCES
        self._stores: dict[str, IdempotentStore] = {
            s["id"]: IdempotentStore(
                config.STORE_MAX_PER_SOURCE, evict_key=lambda a: a["published"]
            )
            for s in sources
        }

    def ingest(self, source_id: str, articles: list[dict]) -> int:
        """Upsert a cycle's articles; returns how many were new."""
        store = self._stores[source_id]
        new = 0
        for article in articles:
            existing = store.get(article["link"])
            if existing is not None:
                existing["published"] = article["published"]  # refresh only
            else:
                store.upsert(article["link"], article)
                new += 1
        return new

    def latest(self, source_id: str, n: int = config.FETCH_LATEST_N) -> list[dict]:
        items = sorted(
            self._stores[source_id].values(),
            key=lambda a: a["published"],
            reverse=True,
        )
        return items[:n]

    def count(self, source_id: str) -> int:
        return len(self._stores[source_id])

    def total(self) -> int:
        return sum(len(s) for s in self._stores.values())

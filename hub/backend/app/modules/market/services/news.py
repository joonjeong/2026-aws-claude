"""REAL per-symbol headlines — Yahoo Finance RSS.

Same fetching pattern as the hub news module: fetch bytes with httpx, parse
with feedparser, accept http(s) links only, per-item try/except. Raises on
upstream HTTP/parse failure — the route degrades to {items: [], error: ...}
instead of caching a failure.
"""
from __future__ import annotations

import logging
from typing import Any

import feedparser
import httpx

from ..core import config
from .kr import is_kr_symbol

log = logging.getLogger("market.news")

_UA = "MarketDesk/0.1 (+claude-lab capstone; headlines only)"


def _yahoo_symbol(symbol: str) -> str:
    return f"{symbol}.KS" if is_kr_symbol(symbol) else symbol


async def fetch_news(symbol: str) -> dict[str, Any]:
    url = config.NEWS_RSS_URL.format(symbol=_yahoo_symbol(symbol))
    async with httpx.AsyncClient(
        timeout=15.0, follow_redirects=True, headers={"User-Agent": _UA}
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
    parsed = feedparser.parse(resp.content)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"unparseable feed: {parsed.bozo_exception!r}")

    items: list[dict[str, str]] = []
    for entry in parsed.entries:
        try:  # one malformed item never drops the batch
            link = (entry.get("link") or "").strip()
            title = (entry.get("title") or "").strip()
            # http(s)만 허용 — javascript: 등 오염 스킴 차단 (news 모듈과 동일 규칙)
            if not title or not link.startswith(("http://", "https://")):
                continue
            items.append({
                "title": title,
                "link": link,
                "published": (entry.get("published") or "").strip(),
            })
        except Exception:  # noqa: BLE001
            log.warning("news[%s]: skipping malformed entry", symbol, exc_info=True)
        if len(items) >= config.NEWS_MAX_ITEMS:
            break
    return {"symbol": symbol, "items": items, "error": None}

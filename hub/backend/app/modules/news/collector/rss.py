"""RSS collection: fetch bytes with httpx, parse with feedparser, normalize.

One labkit.PollingCollector per source (built in main.py) calls
fetch_articles(source); a failing feed only fails its own collector,
so the other three keep polling (structural per-source isolation).
"""
from __future__ import annotations

import calendar
import html
import logging
import re
from datetime import datetime, timezone
from typing import Any

import feedparser
import httpx

from .. import config

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

USER_AGENT = "NewsroomLens/0.1 (+claude-lab capstone; headlines only)"


def strip_html(text: str, max_chars: int = config.SUMMARY_MAX_CHARS) -> str:
    """Remove HTML tags/entities, collapse whitespace, truncate."""
    text = _TAG_RE.sub(" ", text or "")
    text = html.unescape(text)
    text = _WS_RE.sub(" ", text).strip()
    return text[:max_chars]


def _published_iso(entry: Any) -> str:
    """UTC ISO-8601 from the entry's published/updated time (fallback: now)."""
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed is not None:
        dt = datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
    else:
        dt = datetime.now(tz=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def normalize_entries(source_id: str, parsed: Any) -> list[dict]:
    """Newest FETCH_LATEST_N entries → normalized article dicts.

    Per-entry try/except: one malformed item never drops the batch.
    """
    articles: list[dict] = []
    for entry in parsed.entries:
        try:
            link = (entry.get("link") or "").strip()
            title = strip_html(entry.get("title") or "", max_chars=500)
            # http(s)만 허용 — 오염된 피드의 javascript: 등 스킴이 href로 흘러가는 것 차단
            if not link.startswith(("http://", "https://")) or not title:
                continue
            articles.append(
                {
                    "source": source_id,
                    "title": title,
                    "link": link,
                    "published": _published_iso(entry),
                    "summary": strip_html(
                        entry.get("summary") or entry.get("description") or ""
                    ),
                }
            )
        except Exception:  # partial-failure isolation per item
            logger.warning("[%s] skipping malformed entry", source_id, exc_info=True)
    articles.sort(key=lambda a: a["published"], reverse=True)
    return articles[: config.FETCH_LATEST_N]


async def fetch_articles(source: dict) -> list[dict]:
    """One polling cycle for one source. Raises on HTTP/parse failure —
    the owning PollingCollector records the error and retries next cycle."""
    async with httpx.AsyncClient(
        timeout=20.0, follow_redirects=True, headers={"User-Agent": USER_AGENT}
    ) as client:
        resp = await client.get(source["rss_url"])
        resp.raise_for_status()
    parsed = feedparser.parse(resp.content)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"unparseable feed: {parsed.bozo_exception!r}")
    return normalize_entries(source["id"], parsed)

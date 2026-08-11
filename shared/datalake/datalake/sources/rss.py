"""rss — RSS 2.0 표준 상류 (매체 목록 관리형). 생산 kind: news.

이식 원본: hub/backend/app/modules/news/collector/rss.py(normalize_entries).
import 금지.

RSS는 표준 포맷이라 클라이언트가 매체 무관 제네릭 — 수집 대상은 코드가
아니라 목록 파일(rss_feeds.toml)이 관리한다. 매체 추가 = 목록에 한 항목.
env DATALAKE_RSS_FEEDS=<path>로 다른 목록 파일 지정 가능.

봉투는 매체 단위 유지: source = 매체 id, kind = news
(bronze/bbc/news/… — 명령이 하나여도 상류 구분은 보존된다).
권장 스케줄: 120s (hub NEWSROOM_POLL_INTERVAL_S).
"""

from __future__ import annotations

import asyncio
import calendar
import html
import logging
import os
import re
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import feedparser
import httpx

from ..core.source import Record

log = logging.getLogger("datalake.rss")

TIMEOUT_S = 20.0
FETCH_LATEST_N = 15
SUMMARY_MAX_CHARS = 300
CONCURRENCY = 5  # 매체 병렬 상한 — 서로 다른 호스트라 안전

# 수집 주체를 식별 가능하게 — hub(NewsroomLens/0.1)와 다른 자체 UA (설계 §7)
DEFAULT_UA = "DataLake/0.1 (+claude-lab; raw archive)"


def _load_feeds() -> dict[str, dict]:
    override = os.environ.get("DATALAKE_RSS_FEEDS")
    path = Path(override) if override else Path(__file__).with_name("rss_feeds.toml")
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return data["feeds"]


FEEDS: dict[str, dict] = _load_feeds()

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(text: str, max_chars: int = SUMMARY_MAX_CHARS) -> str:
    """HTML 태그/엔티티 제거, 공백 압축, 절단 — hub strip_html과 동일."""
    text = _TAG_RE.sub(" ", text or "")
    text = html.unescape(text)
    text = _WS_RE.sub(" ", text).strip()
    return text[:max_chars]


def _published_iso(entry: Any) -> str:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed is not None:
        dt = datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
    else:
        dt = datetime.now(tz=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def normalize(feed_id: str, xml_text: str | bytes) -> list[dict]:
    """hub normalize_entries()와 동일 — 항목 단위 격리, 최신 15건."""
    parsed = feedparser.parse(xml_text)
    articles: list[dict] = []
    for entry in parsed.entries:
        try:
            link = (entry.get("link") or "").strip()
            title = strip_html(entry.get("title") or "", max_chars=500)
            # http(s)만 허용 — javascript: 등 오염 스킴 차단
            if not link.startswith(("http://", "https://")) or not title:
                continue
            articles.append(
                {
                    "source": feed_id,
                    "title": title,
                    "link": link,
                    "published": _published_iso(entry),
                    "summary": strip_html(
                        entry.get("summary") or entry.get("description") or ""
                    ),
                }
            )
        except Exception:  # 항목 단위 격리
            log.warning("[%s] skipping malformed entry", feed_id, exc_info=True)
    articles.sort(key=lambda a: a["published"], reverse=True)
    return articles[:FETCH_LATEST_N]


class RssClient:
    """매체 하나 = 상류 하나. source = 매체 id, kind = news."""

    def __init__(self, feed_id: str,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        if feed_id not in FEEDS:
            raise ValueError(f"알 수 없는 매체: {feed_id} ({sorted(FEEDS)})")
        self.id = feed_id
        self._feed = FEEDS[feed_id]
        self._transport = transport

    async def fetch(self) -> list[Record]:
        started = time.monotonic()
        user_agent = self._feed.get("user_agent") or DEFAULT_UA
        async with httpx.AsyncClient(
            timeout=TIMEOUT_S, follow_redirects=True,
            headers={"User-Agent": user_agent}, transport=self._transport,
        ) as client:
            resp = await client.get(self._feed["rss_url"])
            resp.raise_for_status()
        return [
            Record(
                source=self.id,
                kind="news",
                payload=resp.text,
                meta={
                    "url": self._feed["rss_url"],
                    "status": resp.status_code,
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                },
            )
        ]


async def fetch_all(feed_ids: list[str] | None = None,
                    transport: httpx.AsyncBaseTransport | None = None,
                    concurrency: int = CONCURRENCY) -> list[Record]:
    """목록의(기본 전체) 매체를 수집 — 매체 단위 실패 격리, 목록 순서 유지."""
    selected = [f.strip() for f in feed_ids] if feed_ids else list(FEEDS)
    unknown = [f for f in selected if f not in FEEDS]
    if unknown:
        raise ValueError(f"알 수 없는 매체: {unknown} ({sorted(FEEDS)})")
    sem = asyncio.Semaphore(concurrency)

    async def one(feed_id: str) -> list[Record]:
        async with sem:
            try:
                return await RssClient(feed_id, transport=transport).fetch()
            except Exception as exc:  # 한 매체 실패가 나머지를 못 죽이게
                log.warning("[%s] fetch failed: %s: %s",
                            feed_id, type(exc).__name__, exc)
                return []

    batches = await asyncio.gather(*(one(f) for f in selected))
    return [rec for batch in batches for rec in batch]


def build(feed_id: str) -> RssClient:
    return RssClient(feed_id)

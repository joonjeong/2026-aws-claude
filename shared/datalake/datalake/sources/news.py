"""news — RSS 15개 매체. 주기·정규화는 hub news 모듈과 동일.

이식 원본: hub/backend/app/modules/news/config.py(SOURCES 값 복사),
collector/rss.py(normalize_entries 이식). import 금지.

Record.payload는 RSS XML 원문(str) — hub는 정규화 후 버리지만 레이크는 보존.
kind = 매체 id (raw/news/<feed_id>/...).
"""

from __future__ import annotations

import calendar
import html
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

import feedparser
import httpx

from ..core.source import Record

log = logging.getLogger("datalake.news")

TIMEOUT_S = 20.0  # 권장 스케줄: 매체당 120s (hub NEWSROOM_POLL_INTERVAL_S)
FETCH_LATEST_N = 15
SUMMARY_MAX_CHARS = 300

# 수집 주체를 식별 가능하게 — hub(NewsroomLens/0.1)와 다른 자체 UA (설계 §7)
DEFAULT_UA = "DataLake/0.1 (+claude-lab; raw archive)"

_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Safari/537.36"
)

# hub news/config.py SOURCES에서 값 복사 (2026-08-11 기준 15개, KBS 보류)
FEEDS: list[dict] = [
    {"id": "bbc", "name": "BBC World", "lang": "en",
     "rss_url": "http://feeds.bbci.co.uk/news/world/rss.xml"},
    {"id": "guardian", "name": "The Guardian World", "lang": "en",
     "rss_url": "https://www.theguardian.com/world/rss"},
    {"id": "nhk", "name": "NHK 국제", "lang": "ja",
     "rss_url": "https://news.web.nhk/n-data/conf/na/rss/cat6.xml"},
    {"id": "yna", "name": "연합뉴스 국제", "lang": "ko",
     "rss_url": "https://www.yna.co.kr/rss/international.xml"},
    {"id": "aljazeera", "name": "Al Jazeera", "lang": "en",
     "rss_url": "https://www.aljazeera.com/xml/rss/all.xml"},
    {"id": "hani", "name": "한겨레", "lang": "ko",
     "rss_url": "https://www.hani.co.kr/rss/"},
    {"id": "khan", "name": "경향신문", "lang": "ko",
     "rss_url": "https://www.khan.co.kr/rss/rssdata/total_news.xml"},
    {"id": "chosun", "name": "조선일보", "lang": "ko",
     "rss_url": "https://www.chosun.com/arc/outboundfeeds/rss/?outputType=xml"},
    {"id": "sbs", "name": "SBS 뉴스(정치)", "lang": "ko",
     "rss_url": "https://news.sbs.co.kr/news/SectionRssFeed.do?sectionId=01"},
    # mk는 일반 UA 403 봇 차단 — 식별 가능한 커스텀 UA로는 200 (hub와 동일 관찰)
    {"id": "mk", "name": "매일경제", "lang": "ko",
     "rss_url": "https://www.mk.co.kr/rss/40300001/"},
    {"id": "hankyung", "name": "한국경제", "lang": "ko",
     "rss_url": "https://www.hankyung.com/feed/economy"},
    {"id": "npr", "name": "NPR", "lang": "en",
     "rss_url": "https://feeds.npr.org/1001/rss.xml"},
    {"id": "nyt", "name": "NYT", "lang": "en",
     "rss_url": "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml"},
    {"id": "fox", "name": "Fox News", "lang": "en",
     "rss_url": "https://feeds.foxnews.com/foxnews/latest"},
    # WaPo는 비브라우저 UA를 403으로 차단 — 피드 리더 관행대로 브라우저 UA
    {"id": "wapo", "name": "Washington Post", "lang": "en",
     "rss_url": "https://feeds.washingtonpost.com/rss/world",
     "user_agent": _BROWSER_UA},
]

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


class NewsClient:
    id = "news"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def fetch_feed(self, feed: dict) -> list[Record]:
        started = time.monotonic()
        user_agent = feed.get("user_agent") or DEFAULT_UA
        async with httpx.AsyncClient(
            timeout=TIMEOUT_S, follow_redirects=True,
            headers={"User-Agent": user_agent}, transport=self._transport,
        ) as client:
            resp = await client.get(feed["rss_url"])
            resp.raise_for_status()
        return [
            Record(
                source=self.id,
                kind=feed["id"],
                payload=resp.text,
                meta={
                    "url": feed["rss_url"],
                    "status": resp.status_code,
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                },
            )
        ]

    async def fetch(self, feed_ids: list[str] | None = None) -> list[Record]:
        """선택한(기본 전체) 매체를 순차 수집 — 매체 단위 실패 격리."""
        selected = ({f.strip() for f in feed_ids} if feed_ids else None)
        records: list[Record] = []
        for feed in FEEDS:
            if selected is not None and feed["id"] not in selected:
                continue
            try:
                records.extend(await self.fetch_feed(feed))
            except Exception as exc:  # 한 매체 실패가 나머지를 못 죽이게
                log.warning("[%s] fetch failed: %s: %s",
                            feed["id"], type(exc).__name__, exc)
        return records


def build() -> NewsClient:
    return NewsClient()

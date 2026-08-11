"""uv run datalake-rss — RSS 목록 일괄 수집 (자기완결). 권장 120s.

수집 대상은 rss_feeds.toml이 관리 (env DATALAKE_RSS_FEEDS로 교체).
파이프라인: 매체별 fetch(병렬 5, 실패 격리) → parse(순수 map/filter) →
landing/<매체>/news + bronze/news_articles. 정규화는 hub news와 동일 의미.
"""

from __future__ import annotations

import asyncio
import calendar
import html
import json
import logging
import os
import re
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Optional

import feedparser
import httpx
import typer

log = logging.getLogger("datalake.rss")

TIMEOUT_S = 20.0
FETCH_LATEST_N = 15
SUMMARY_MAX_CHARS = 300
CONCURRENCY = 5
DEFAULT_UA = "DataLake/0.1 (+claude-lab; raw archive)"
DEFAULT_ROOT = Path(os.environ.get(
    "DATALAKE_ROOT", str(Path(__file__).resolve().parent.parent / "data")))


def load_feeds() -> dict[str, dict]:
    override = os.environ.get("DATALAKE_RSS_FEEDS")
    path = Path(override) if override else Path(__file__).with_name("rss_feeds.toml")
    return tomllib.loads(path.read_text(encoding="utf-8"))["feeds"]


# ── 순수 파싱 (hub news normalize_entries와 동일 의미) ───────────────
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(text: str, max_chars: int = SUMMARY_MAX_CHARS) -> str:
    return _WS_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", text or ""))).strip()[:max_chars]


def _published_iso(entry) -> str:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    dt = (datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
          if parsed is not None else datetime.now(tz=timezone.utc))
    return dt.isoformat().replace("+00:00", "Z")


def _to_article(feed_id: str, entry) -> dict | None:
    """RSS entry → news_articles 행. 부적격은 None (filter로 제거)."""
    try:
        link = (entry.get("link") or "").strip()
        title = strip_html(entry.get("title") or "", max_chars=500)
        if not link.startswith(("http://", "https://")) or not title:
            return None  # javascript: 등 오염 스킴·무제목 차단
        return {
            "source": feed_id,
            "title": title,
            "link": link,
            "published": _published_iso(entry),
            "summary": strip_html(entry.get("summary") or entry.get("description") or ""),
        }
    except Exception:  # 항목 단위 격리
        log.warning("[%s] skipping malformed entry", feed_id, exc_info=True)
        return None


def parse(feed_id: str, xml_text: str | bytes) -> list[dict]:
    entries = feedparser.parse(xml_text).entries
    articles = [a for a in (_to_article(feed_id, e) for e in entries) if a]
    return sorted(articles, key=lambda a: a["published"], reverse=True)[:FETCH_LATEST_N]


# ── 랜딩 ────────────────────────────────────────────────────────────
def _jsonl(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _append(path: Path, lines: list[str]) -> None:
    if not lines:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _part(root: Path, zone: str, *dirs: str, ts: float) -> Path:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return root.joinpath(zone, *dirs, f"dt={dt:%Y-%m-%d}", f"part-{dt:%H}.jsonl")


def land(root: Path, feed_id: str, ts: float, xml_text: str, meta: dict) -> int:
    """매체 하나의 봉투 + bronze 행 append. 적재 행 수 반환."""
    rows = [{**a, "first_seen": ts} for a in parse(feed_id, xml_text)]
    envelope = {
        "fetched_at": datetime.fromtimestamp(ts, tz=timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": feed_id, "kind": "news", "meta": meta, "payload": xml_text,
    }
    _append(_part(root, "landing", feed_id, "news", ts=ts), [_jsonl(envelope)])
    _append(_part(root, "bronze", "news_articles", ts=ts),
            [_jsonl(r) for r in rows])
    return len(rows)


# ── 수집 ─────────────────────────────────────────────────────────────
async def fetch_feed(client: httpx.AsyncClient, feed_id: str,
                     feed: dict) -> tuple[str, str, dict] | None:
    """(feed_id, xml, meta) — 실패는 None (매체 단위 격리)."""
    started = time.monotonic()
    try:
        resp = await client.get(
            feed["rss_url"],
            headers={"User-Agent": feed.get("user_agent") or DEFAULT_UA})
        resp.raise_for_status()
        return feed_id, resp.text, {
            "url": feed["rss_url"], "status": resp.status_code,
            "elapsed_ms": int((time.monotonic() - started) * 1000)}
    except Exception as exc:
        log.warning("[%s] fetch failed: %s: %s", feed_id, type(exc).__name__, exc)
        return None


async def collect(root: Path, feed_ids: list[str] | None = None,
                  transport: httpx.AsyncBaseTransport | None = None) -> int:
    feeds = load_feeds()
    selected = [f.strip() for f in feed_ids] if feed_ids else list(feeds)
    unknown = [f for f in selected if f not in feeds]
    if unknown:
        raise ValueError(f"알 수 없는 매체: {unknown} ({sorted(feeds)})")

    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(client, fid):
        async with sem:
            return await fetch_feed(client, fid, feeds[fid])

    async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=True,
                                 transport=transport) as client:
        fetched = await asyncio.gather(*(one(client, f) for f in selected))

    ts = time.time()
    total = sum(land(root, fid, ts, xml, meta)
                for fid, xml, meta in filter(None, fetched))
    ok = sum(1 for r in fetched if r)
    log.info("[rss] 매체 %d/%d · bronze %d행 → %s", ok, len(selected), total, root)
    return 0


def cli(
    output: Annotated[Optional[Path], typer.Option(
        help="레이크 루트 (기본: env DATALAKE_ROOT)")] = None,
    feeds: Annotated[Optional[str], typer.Option(
        help="쉼표 구분 매체 id 선택 (기본: 목록 전체)")] = None,
    list_feeds: Annotated[bool, typer.Option(
        "--list", help="수집 대상 목록 출력 후 종료")] = False,
) -> None:
    """RSS 목록 일괄 수집 → landing + bronze."""
    if list_feeds:
        for fid, feed in load_feeds().items():
            print(f"{fid:12s} {feed['lang']:2s}  {feed['name']}  {feed['rss_url']}")
        return
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        asyncio.run(collect(output or DEFAULT_ROOT,
                            feeds.split(",") if feeds else None))
    except Exception as exc:
        log.error("실패: %s: %s", type(exc).__name__, exc)
        raise typer.Exit(1)


def main() -> None:
    typer.run(cli)


if __name__ == "__main__":
    main()

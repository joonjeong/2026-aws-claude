"""uv run datalake-youtube — YouTube 인기 동영상(KR) 수집 (자기완결). 권장 60s.

YT_API_KEY 필요 (없으면 종료 코드 2). 키·응답 본문은 로그·봉투 meta에
싣지 않는다 (hub 격리 규칙과 동일).
파이프라인: fetch → parse(순수 map/filter) → landing/youtube/trend +
bronze/trend_videos·trend_video_stats (60s 버킷 ts — 재구축 멱등).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

log = logging.getLogger("datalake.youtube")

SOURCE = "youtube"
API_URL = "https://www.googleapis.com/youtube/v3/videos"
REGION_CODE = "KR"
MAX_RESULTS = 30
TIMEOUT_S = 15.0
BUCKET_S = 60.0  # hub POLL_INTERVAL_S — stats ts 정렬값
DEFAULT_ROOT = Path(os.environ.get(
    "DATALAKE_ROOT", str(Path(__file__).resolve().parent.parent / "data")))


# ── 순수 파싱 (hub trend _normalize_item과 동일 의미) ────────────────
def _count(value) -> int:
    try:
        n = int(str(value))
        return n if n >= 0 else 0
    except (TypeError, ValueError):
        return 0


def to_item(raw) -> dict | None:
    try:
        snippet = raw.get("snippet") or {}
        stats = raw.get("statistics") or {}
        thumbs = snippet.get("thumbnails") or {}
        thumb = thumbs.get("medium") or thumbs.get("high") or thumbs.get("default") or {}
        return {
            "video_id": str(raw["id"]),
            "title": str(snippet.get("title", "")),
            "channel": str(snippet.get("channelTitle", "")),
            "category_id": str(snippet.get("categoryId", "")),
            "thumbnail": str(thumb.get("url", "")),
            "view_count": _count(stats.get("viewCount")),
            "like_count": _count(stats.get("likeCount")),
            "published_at": str(snippet.get("publishedAt", "")),
        }
    except Exception:
        log.warning("item skipped", exc_info=True)
        return None


def parse(payload: dict) -> list[dict]:
    return [i for i in map(to_item, payload.get("items") or []) if i]


def to_video_row(item: dict, ts: float) -> dict:
    return {**{k: item[k] for k in ("video_id", "title", "channel", "category_id",
                                    "thumbnail", "published_at")},
            "first_seen": ts, "last_seen": ts}


def to_stat_row(item: dict, rank: int, bucket_ts: float) -> dict:
    return {"video_id": item["video_id"], "ts": bucket_ts, "rank": rank,
            "view_count": item["view_count"], "like_count": item["like_count"]}


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


def land(root: Path, ts: float, payload: dict, meta: dict) -> int:
    items = parse(payload)
    bucket_ts = float(int(ts // BUCKET_S) * BUCKET_S)
    envelope = {
        "fetched_at": datetime.fromtimestamp(ts, tz=timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": SOURCE, "kind": "trend", "meta": meta, "payload": payload,
    }
    _append(_part(root, "landing", SOURCE, "trend", ts=ts), [_jsonl(envelope)])
    _append(_part(root, "bronze", "trend_videos", ts=ts),
            [_jsonl(to_video_row(i, ts)) for i in items])
    _append(_part(root, "bronze", "trend_video_stats", ts=ts),
            [_jsonl(to_stat_row(i, rank, bucket_ts))
             for rank, i in enumerate(items, start=1)])
    return len(items)


# ── 수집 ─────────────────────────────────────────────────────────────
async def collect(root: Path, api_key: str,
                  transport: httpx.AsyncBaseTransport | None = None) -> int:
    started = time.monotonic()
    async with httpx.AsyncClient(timeout=TIMEOUT_S, transport=transport) as client:
        resp = await client.get(API_URL, params={
            "part": "snippet,statistics", "chart": "mostPopular",
            "regionCode": REGION_CODE, "maxResults": MAX_RESULTS, "key": api_key,
        })
    if resp.status_code != 200:
        # 본문은 로그로만, 예외에는 상태코드만 (키·프로젝트 정보 비유출)
        log.error("youtube upstream %s: %s", resp.status_code, resp.text[:2000])
        raise RuntimeError(f"youtube upstream status {resp.status_code}")
    ts = time.time()
    meta = {"region": REGION_CODE, "status": resp.status_code,
            "elapsed_ms": int((time.monotonic() - started) * 1000)}
    n = land(root, ts, resp.json(), meta)
    log.info("[%s] 봉투 1개 · 영상 %d개 → %s", SOURCE, n, root)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="datalake-youtube", description=__doc__)
    parser.add_argument("--output", default=None, metavar="ROOT",
                        help="레이크 루트 (기본: env DATALAKE_ROOT)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    api_key = os.environ.get("YT_API_KEY")
    if not api_key:
        log.error("youtube 비활성: YT_API_KEY 미설정")
        return 2
    try:
        return asyncio.run(collect(
            Path(args.output) if args.output else DEFAULT_ROOT, api_key))
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        log.error("실패: %s: %s", type(exc).__name__, exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

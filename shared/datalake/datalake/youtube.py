"""YouTube 인기 동영상(KR) 수집 (자기완결). 권장 60s.

YT_API_KEY 필요 (없으면 종료 코드 2). 키·응답 본문은 로그·봉투 meta에
싣지 않는다. 파이프라인: fetch → TrendItem 모델 파싱 →
landing/youtube/trend + bronze/trend_videos·trend_video_stats.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Optional

import httpx
import typer
from pydantic import BaseModel, BeforeValidator

log = logging.getLogger("datalake.youtube")

SOURCE = "youtube"
API_URL = "https://www.googleapis.com/youtube/v3/videos"
REGION_CODE = "KR"
MAX_RESULTS = 30
TIMEOUT_S = 15.0
BUCKET_S = 60.0  # hub POLL_INTERVAL_S — stats ts 정렬값
DEFAULT_ROOT = Path(os.environ.get(
    "DATALAKE_ROOT", str(Path(__file__).resolve().parent.parent / "data")))


# ── bronze 행 모델 — 문자열 카운트·음수는 pydantic 검증기가 방어 ─────
def _count(v):
    try:
        return max(0, int(str(v)))
    except (TypeError, ValueError):
        return 0


Count = Annotated[int, BeforeValidator(_count)]
Text = Annotated[str, BeforeValidator(lambda v: str(v) if v is not None else "")]


class TrendItem(BaseModel):
    video_id: Text
    title: Text = ""
    channel: Text = ""
    category_id: Text = ""
    thumbnail: Text = ""
    view_count: Count = 0
    like_count: Count = 0
    published_at: Text = ""


def to_item(raw) -> dict | None:
    try:
        snippet = raw.get("snippet") or {}
        thumbs = snippet.get("thumbnails") or {}
        thumb = thumbs.get("medium") or thumbs.get("high") or thumbs.get("default") or {}
        stats = raw.get("statistics") or {}
        return TrendItem(
            video_id=raw["id"], title=snippet.get("title"),
            channel=snippet.get("channelTitle"),
            category_id=snippet.get("categoryId"), thumbnail=thumb.get("url"),
            view_count=stats.get("viewCount"), like_count=stats.get("likeCount"),
            published_at=snippet.get("publishedAt"),
        ).model_dump()
    except Exception:
        log.warning("item skipped", exc_info=True)
        return None


def parse(payload: dict) -> list[dict]:
    return [i for i in map(to_item, payload.get("items") or []) if i]


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
            [_jsonl({**{k: i[k] for k in ("video_id", "title", "channel",
                                          "category_id", "thumbnail",
                                          "published_at")},
                     "first_seen": ts, "last_seen": ts}) for i in items])
    _append(_part(root, "bronze", "trend_video_stats", ts=ts),
            [_jsonl({"video_id": i["video_id"], "ts": bucket_ts, "rank": rank,
                     "view_count": i["view_count"], "like_count": i["like_count"]})
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
    meta = {"region": REGION_CODE, "status": resp.status_code,
            "elapsed_ms": int((time.monotonic() - started) * 1000)}
    n = land(root, time.time(), resp.json(), meta)
    log.info("[%s] 봉투 1개 · 영상 %d개 → %s", SOURCE, n, root)
    return 0


def cli(output: Annotated[Optional[Path], typer.Option(
        help="레이크 루트 (기본: env DATALAKE_ROOT)")] = None) -> None:
    """YouTube 인기 동영상(KR) 1회 수집 → landing + bronze."""
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    api_key = os.environ.get("YT_API_KEY")
    if not api_key:
        log.error("youtube 비활성: YT_API_KEY 미설정")
        raise typer.Exit(2)
    try:
        asyncio.run(collect(output or DEFAULT_ROOT, api_key))
    except Exception as exc:
        log.error("실패: %s: %s", type(exc).__name__, exc)
        raise typer.Exit(1)


def main() -> None:
    typer.run(cli)


if __name__ == "__main__":
    main()

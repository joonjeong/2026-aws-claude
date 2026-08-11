"""uv run datalake-usgs-feed — USGS 지진 피드 수집 (자기완결). 권장 60s.

파이프라인: fetch → parse(순수 map/filter) → landing/usgs_feed/quake +
bronze/quake_events. 정규화 의미는 hub quake 모듈과 동일.
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

log = logging.getLogger("datalake.usgs_feed")

SOURCE = "usgs_feed"
FEED_URL = os.environ.get(
    "DATALAKE_USGS_FEED_URL",
    "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson",
)
TIMEOUT_S = 10.0
DEFAULT_ROOT = Path(os.environ.get(
    "DATALAKE_ROOT", str(Path(__file__).resolve().parent.parent / "data")))


# ── 순수 파싱 (hub quake normalize와 동일 의미) ──────────────────────
def _float(value, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if result == result else default  # NaN -> default


def _int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def to_row(feature) -> dict | None:
    """GeoJSON feature → quake_events 행. 비정상은 None (filter로 제거)."""
    try:
        if not feature.get("id"):
            return None
        props = feature.get("properties") or {}
        coords = list(((feature.get("geometry") or {}).get("coordinates") or [])) + [0, 0, 0]
        place = props.get("place")
        return {
            "id": str(feature["id"]),
            "mag": _float(props.get("mag")),
            "place": str(place) if place else "unknown",
            "time": _int(props.get("time")),
            "lon": _float(coords[0]),
            "lat": _float(coords[1]),
            "depth_km": _float(coords[2]),
        }
    except Exception:  # 깨진 feature 격리
        log.warning("skipping malformed feature", exc_info=True)
        return None


def parse(payload: dict) -> list[dict]:
    return [row for row in map(to_row, payload.get("features") or []) if row]


# ── 랜딩 (파일 append — 자기완결 헬퍼) ──────────────────────────────
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


def land(root: Path, ts: float, payload: dict, meta: dict,
         rows: list[dict]) -> int:
    """landing 봉투 1줄 + bronze 행 N줄 append. 적재 행 수 반환."""
    envelope = {
        "fetched_at": datetime.fromtimestamp(ts, tz=timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": SOURCE, "kind": "quake", "meta": meta, "payload": payload,
    }
    _append(_part(root, "landing", SOURCE, "quake", ts=ts), [_jsonl(envelope)])
    _append(_part(root, "bronze", "quake_events", ts=ts),
            [_jsonl(r) for r in rows])
    return len(rows)


# ── 수집 ─────────────────────────────────────────────────────────────
async def collect(root: Path,
                  transport: httpx.AsyncBaseTransport | None = None) -> int:
    started = time.monotonic()
    async with httpx.AsyncClient(timeout=TIMEOUT_S, transport=transport) as client:
        resp = await client.get(FEED_URL)
        resp.raise_for_status()
        payload = resp.json()
    ts = time.time()
    meta = {"url": FEED_URL, "status": resp.status_code,
            "elapsed_ms": int((time.monotonic() - started) * 1000)}
    n = land(root, ts, payload, meta, parse(payload))
    log.info("[%s] 봉투 1개 · bronze %d행 → %s", SOURCE, n, root)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="datalake-usgs-feed", description=__doc__)
    parser.add_argument("--output", default=None, metavar="ROOT",
                        help="레이크 루트 (기본: env DATALAKE_ROOT)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        return asyncio.run(collect(Path(args.output) if args.output else DEFAULT_ROOT))
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        log.error("실패: %s: %s", type(exc).__name__, exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

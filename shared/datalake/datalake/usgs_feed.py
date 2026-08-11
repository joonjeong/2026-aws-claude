"""USGS 지진 피드 수집 (자기완결). 권장 60s.

파이프라인: fetch → QuakeEvent 모델 파싱(캐스팅·폴백은 pydantic) →
landing/usgs_feed/quake + bronze/quake_events. hub quake와 동일 의미.
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

log = logging.getLogger("datalake.usgs_feed")

SOURCE = "usgs_feed"
FEED_URL = os.environ.get(
    "DATALAKE_USGS_FEED_URL",
    "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson",
)
TIMEOUT_S = 10.0
DEFAULT_ROOT = Path(os.environ.get(
    "DATALAKE_ROOT", str(Path(__file__).resolve().parent.parent / "data")))


# ── bronze 행 모델 — 캐스팅·폴백은 필드 선언으로 (pydantic 이디엄) ────
def _or(default):
    """실패·NaN → 기본값 코어서 (BeforeValidator 팩토리)."""
    def coerce(v):
        try:
            f = float(v)
            return default if f != f else v  # NaN 방어
        except (TypeError, ValueError):
            return default
    return BeforeValidator(coerce)


F0 = Annotated[float, _or(0.0)]                # float 폴백 0.0
I0 = Annotated[int, _or(0)]                    # int 폴백 0
PlaceStr = Annotated[str, BeforeValidator(lambda v: str(v) if v else "unknown")]


class QuakeEvent(BaseModel):
    id: str
    mag: F0 = 0.0
    place: PlaceStr = "unknown"
    time: I0 = 0
    lon: F0 = 0.0
    lat: F0 = 0.0
    depth_km: F0 = 0.0


def to_row(feature) -> dict | None:
    """GeoJSON feature → 행. 비정상은 None (filter로 제거)."""
    try:
        if not feature.get("id"):
            return None
        props = feature.get("properties") or {}
        coords = list(((feature.get("geometry") or {}).get("coordinates") or [])) + [0, 0, 0]
        return QuakeEvent(
            id=feature["id"], mag=props.get("mag"), place=props.get("place"),
            time=props.get("time"), lon=coords[0], lat=coords[1],
            depth_km=coords[2],
        ).model_dump()
    except Exception:  # 깨진 feature 격리
        log.warning("skipping malformed feature", exc_info=True)
        return None


def parse(payload: dict) -> list[dict]:
    return [row for row in map(to_row, payload.get("features") or []) if row]


# ── 랜딩 (자기완결 헬퍼) ────────────────────────────────────────────
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
    meta = {"url": FEED_URL, "status": resp.status_code,
            "elapsed_ms": int((time.monotonic() - started) * 1000)}
    n = land(root, time.time(), payload, meta, parse(payload))
    log.info("[%s] 봉투 1개 · bronze %d행 → %s", SOURCE, n, root)
    return 0


def cli(output: Annotated[Optional[Path], typer.Option(
        help="레이크 루트 (기본: env DATALAKE_ROOT)")] = None) -> None:
    """USGS 지진 피드 1회 수집 → landing + bronze."""
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        asyncio.run(collect(output or DEFAULT_ROOT))
    except Exception as exc:
        log.error("실패: %s: %s", type(exc).__name__, exc)
        raise typer.Exit(1)


def main() -> None:
    typer.run(cli)


if __name__ == "__main__":
    main()

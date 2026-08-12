"""uv run datalake-adsblol — adsb.lol 항공 트래픽 수집 (자기완결).

권장: --scope regions 60s / --scope global 600s. 프리셋 4개는 순차 1.1s
간격 (병렬 4요청 → 420, hub 실측). 원시 URL 조립 필수 (%2C·jv2= 는 400).
파이프라인: bbox별 fetch → parse(순수 map/filter, readsb v2) →
landing/adsblol/contrail_* + bronze/contrail_aircraft·contrail_positions.
전세계 스냅샷은 landing만 (bronze 홍수 방지 — hub와 동일).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Annotated, Optional

import httpx
import typer

log = logging.getLogger("datalake.adsblol")

SOURCE = "adsblol"
BASE_URL = os.environ.get("DATALAKE_ADSBLOL_URL", "https://re-api.adsb.lol/")
TIMEOUT_S = 15.0
REGION_SPACING_S = 1.1
USER_AGENT = "DataLake/0.1 (+claude-lab; raw archive)"
DEFAULT_ROOT = Path(os.environ.get(
    "DATALAKE_ROOT", str(Path(__file__).resolve().parent.parent / "data")))

GLOBAL_BBOX = (-90.0, -180.0, 90.0, 180.0)
# bbox = (lat_min, lon_min, lat_max, lon_max) — hub contrail 프리셋과 동일
PRESETS: dict[str, tuple] = {
    "kr": (30.0, 120.0, 45.0, 135.0),
    "japan": (30.0, 128.0, 43.0, 146.0),
    "europe": (43.0, -5.0, 55.0, 20.0),
    "us-east": (25.0, -90.0, 45.0, -70.0),
}

FT_TO_M = 0.3048
KT_TO_MS = 0.514444


def url_for(bbox: tuple) -> str:
    """re-api는 lat_min,lat_max,lon_min,lon_max 순서 + 인코딩 없는 원시 쿼리."""
    lat_min, lon_min, lat_max, lon_max = bbox
    return f"{BASE_URL}?box={lat_min},{lat_max},{lon_min},{lon_max}&jv2"


# ── 순수 파싱 (hub contrail normalize_readsb와 동일 의미) ────────────
def to_flight(a, now: float) -> dict | None:
    try:
        if not a.get("hex") or a.get("lat") is None or a.get("lon") is None:
            return None
        alt = a.get("alt_baro")
        on_ground = alt == "ground"
        seen_pos = a.get("seen_pos")
        track = a.get("track", a.get("calc_track"))
        gs = a.get("gs")
        return {
            "id": str(a["hex"]),
            "callsign": (a.get("flight") or "").strip() or None,
            "origin_country": None,  # readsb 응답에는 국가 정보 없음
            "ts": now - float(seen_pos) if seen_pos is not None else now,
            "lon": float(a["lon"]),
            "lat": float(a["lat"]),
            "alt_m": None if on_ground or alt is None else float(alt) * FT_TO_M,
            "on_ground": on_ground,
            "velocity_ms": None if gs is None else float(gs) * KT_TO_MS,
            "track_deg": None if track is None else float(track),
            "type": a.get("t") or None,
            "reg": a.get("r") or None,
        }
    except Exception:
        log.warning("skipping malformed ac entry", exc_info=True)
        return None


def parse(payload: dict, now: float) -> list[dict]:
    return [f for f in (to_flight(a, now) for a in payload.get("ac") or []) if f]


def to_aircraft_row(f: dict) -> dict:
    # 공급자 필드 합집합: origin_country(opensky)·type/reg(adsblol) — 없는 쪽 null
    return {"icao24": f["id"], "callsign": f["callsign"],
            "origin_country": f["origin_country"],
            "type": f["type"], "reg": f["reg"],
            "first_seen": f["ts"], "last_seen": f["ts"]}


def to_position_row(f: dict) -> dict:
    return {k: f[k] for k in ("ts", "lon", "lat", "alt_m", "velocity_ms",
                              "track_deg", "on_ground")} | {"icao24": f["id"]}


# ── 랜딩 ────────────────────────────────────────────────────────────
def _jsonl(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _row(d: dict) -> str:
    """bronze 행 직렬화 — 값 없는(None) 키는 생략 (스키마는 소비 측 union)."""
    return _jsonl({k: v for k, v in d.items() if v is not None})


def _append(path: Path, lines: list[str]) -> None:
    if not lines:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _part(root: Path, zone: str, *dirs: str, ts: float) -> Path:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return root.joinpath(zone, *dirs, f"dt={dt:%Y-%m-%d}", f"part-{dt:%H}.jsonl")


def land(root: Path, kind: str, ts: float, payload: dict, meta: dict,
         bronze: bool, keep_landing: bool = False) -> int:
    """kind 하나의 봉투 + (지역 스냅샷이면) bronze 행 append."""
    if keep_landing:  # 원본 봉투 보존은 옵트인 (--landing)
        envelope = {
            "fetched_at": datetime.fromtimestamp(ts, tz=timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": SOURCE, "kind": kind, "meta": meta, "payload": payload,
        }
        _append(_part(root, "landing", SOURCE, kind, ts=ts), [_jsonl(envelope)])
    if not bronze:
        return 0  # 전세계 스냅샷은 landing 전용 (bronze 홍수 방지)
    flights = parse(payload, now=ts)
    # 공급자는 source= 파티션 경로가 담는다 (행 중복 저장 없음 — Hive 관례)
    _append(_part(root, "bronze", "contrail_aircraft", f"source={SOURCE}", ts=ts),
            [_row(to_aircraft_row(f)) for f in flights])
    _append(_part(root, "bronze", "contrail_positions", f"source={SOURCE}", ts=ts),
            [_row(to_position_row(f)) for f in flights])
    return len(flights)


# ── 수집 ─────────────────────────────────────────────────────────────
async def _fetch(client: httpx.AsyncClient, bbox: tuple) -> tuple[dict, dict]:
    started = time.monotonic()
    resp = await client.get(url_for(bbox))
    resp.raise_for_status()
    return resp.json(), {
        "bbox": ",".join(str(v) for v in bbox), "status": resp.status_code,
        "elapsed_ms": int((time.monotonic() - started) * 1000)}


async def collect(root: Path, scope: str, keep_landing: bool = False,
                  transport: httpx.AsyncBaseTransport | None = None) -> int:
    total = 0
    async with httpx.AsyncClient(timeout=TIMEOUT_S, transport=transport,
                                 headers={"User-Agent": USER_AGENT}) as client:
        if scope in ("global", "both") and not keep_landing:
            log.warning("전세계 스냅샷은 landing 전용 — --landing 없이는 저장되지 않음")
        if scope in ("global", "both"):
            payload, meta = await _fetch(client, GLOBAL_BBOX)
            land(root, "contrail_global", time.time(), payload, meta,
                 bronze=False, keep_landing=keep_landing)
        if scope in ("regions", "both"):
            for preset, bbox in PRESETS.items():
                await asyncio.sleep(REGION_SPACING_S)  # 상류 빈도 제한 예의
                payload, meta = await _fetch(client, bbox)
                total += land(root, f"contrail_region_{preset}", time.time(),
                              payload, meta, bronze=True,
                              keep_landing=keep_landing)
    log.info("[%s] scope=%s · bronze %d행 → %s", SOURCE, scope, total, root)
    return 0


class Scope(str, Enum):
    global_ = "global"
    regions = "regions"
    both = "both"


def cli(
    output: Annotated[Optional[Path], typer.Option(
        help="레이크 루트 (기본: env DATALAKE_ROOT)")] = None,
    scope: Annotated[Scope, typer.Option(help="수집 범위")] = Scope.both,
    landing: Annotated[bool, typer.Option(
        "--landing", help="원본 봉투를 landing 존에도 보존")] = False,
) -> None:
    """항공 트래픽 1회 수집 → landing + bronze."""
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        asyncio.run(collect(output or DEFAULT_ROOT, scope.value, landing))
    except Exception as exc:
        log.error("실패: %s: %s", type(exc).__name__, exc)
        raise typer.Exit(1)


def main() -> None:
    typer.run(cli)


if __name__ == "__main__":
    main()

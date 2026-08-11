"""uv run datalake-opensky — OpenSky 항공 트래픽 수집 (자기완결).

adsblol과 같은 kind(contrail_*)를 생산 — bronze 테이블도 동일 (제공자 중립).
OAuth2 client-credentials (DATALAKE_OPENSKY_CLIENT_ID/SECRET), 미설정·실패
시 익명 감속 모드. 토큰은 상태 파일(0600)에 캐시 — 만료 60s 전 갱신.
주의: 데이터센터 IP 차단 실측 — 클라우드 배치는 datalake-adsblol 사용.
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

log = logging.getLogger("datalake.opensky")

SOURCE = "opensky"
STATES_URL = os.environ.get("DATALAKE_OPENSKY_URL",
                            "https://opensky-network.org/api/states/all")
TOKEN_URL = os.environ.get(
    "DATALAKE_OPENSKY_TOKEN_URL",
    "https://auth.opensky-network.org/auth/realms/opensky-network"
    "/protocol/openid-connect/token",
)
TIMEOUT_S = 15.0
REGION_SPACING_S = 1.1
USER_AGENT = "DataLake/0.1 (+claude-lab; raw archive)"
DEFAULT_ROOT = Path(os.environ.get(
    "DATALAKE_ROOT", str(Path(__file__).resolve().parent.parent / "data")))

# bbox = (lat_min, lon_min, lat_max, lon_max) — adsblol과 동일 프리셋
PRESETS: dict[str, tuple] = {
    "kr": (30.0, 120.0, 45.0, 135.0),
    "japan": (30.0, 128.0, 43.0, 146.0),
    "europe": (43.0, -5.0, 55.0, 20.0),
    "us-east": (25.0, -90.0, 45.0, -70.0),
}


# ── 순수 파싱 (hub contrail normalize_states와 동일 의미) ────────────
# states 인덱스: 0 icao24, 1 callsign, 2 origin_country, 3 time_position,
# 4 last_contact, 5 lon, 6 lat, 7 baro_alt(m), 8 on_ground, 9 velocity(m/s),
# 10 true_track(deg)
def to_flight(s, now: float) -> dict | None:
    try:
        if not s[0] or s[5] is None or s[6] is None:
            return None
        return {
            "id": str(s[0]),
            "callsign": (s[1] or "").strip() or None,
            "origin_country": s[2],
            "ts": float(s[3] or s[4] or now),
            "lon": float(s[5]),
            "lat": float(s[6]),
            "alt_m": None if s[7] is None else float(s[7]),
            "on_ground": bool(s[8]),
            "velocity_ms": None if s[9] is None else float(s[9]),
            "track_deg": None if s[10] is None else float(s[10]),
            "type": None, "reg": None,  # OpenSky에는 기종·등록부호 없음
        }
    except Exception:
        log.warning("skipping malformed state entry", exc_info=True)
        return None


def parse(payload: dict, now: float) -> list[dict]:
    return [f for f in (to_flight(s, now) for s in payload.get("states") or []) if f]


def to_aircraft_row(f: dict) -> dict:
    # 공급자 필드 합집합: origin_country(opensky)·type/reg(adsblol) — 없는 쪽 null
    return {"icao24": f["id"], "callsign": f["callsign"],
            "origin_country": f["origin_country"],
            "type": f["type"], "reg": f["reg"],
            "first_seen": f["ts"], "last_seen": f["ts"]}


def to_position_row(f: dict) -> dict:
    return {k: f[k] for k in ("ts", "lon", "lat", "alt_m", "velocity_ms",
                              "track_deg", "on_ground")} | {"icao24": f["id"]}


# ── 토큰 (상태 파일 캐시, 0600 — 익명 폴백) ──────────────────────────
def read_cached_token(state_path: Path | None) -> str | None:
    if state_path is None or not state_path.exists():
        return None
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        if float(data["expires_at"]) > time.time() + 60:  # 만료 60s 전 갱신
            return str(data["access_token"])
    except Exception:
        log.warning("opensky token state unreadable", exc_info=True)
    return None


def write_token(state_path: Path | None, token: str, expires_in: float) -> None:
    if state_path is None:
        return
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"access_token": token,
                          "expires_at": time.time() + expires_in})
    # 자격증명 파일은 0600 강제 — 타 사용자 읽기 차단
    fd = os.open(state_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, payload.encode("utf-8"))
    finally:
        os.close(fd)


async def get_token(client: httpx.AsyncClient,
                    state_path: Path | None) -> str | None:
    client_id = os.environ.get("DATALAKE_OPENSKY_CLIENT_ID")
    client_secret = os.environ.get("DATALAKE_OPENSKY_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None  # 익명 감속 모드
    cached = read_cached_token(state_path)
    if cached is not None:
        return cached
    try:
        resp = await client.post(TOKEN_URL, data={
            "grant_type": "client_credentials",
            "client_id": client_id, "client_secret": client_secret,
        })
        resp.raise_for_status()
        data = resp.json()
        write_token(state_path, str(data["access_token"]),
                    float(data.get("expires_in", 1800)))
        return str(data["access_token"])
    except Exception as exc:  # 토큰 실패가 수집을 막지 않는다 (hub 동일)
        log.warning("opensky token fetch failed (anonymous fallback): %s", exc)
        return None


# ── 랜딩 (adsblol과 동일 구조) ──────────────────────────────────────
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


def land(root: Path, kind: str, ts: float, payload: dict, meta: dict,
         bronze: bool) -> int:
    envelope = {
        "fetched_at": datetime.fromtimestamp(ts, tz=timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": SOURCE, "kind": kind, "meta": meta, "payload": payload,
    }
    _append(_part(root, "landing", SOURCE, kind, ts=ts), [_jsonl(envelope)])
    if not bronze:
        return 0  # 전세계 스냅샷은 landing만 (홍수 방지)
    flights = parse(payload, now=ts)
    # 모든 bronze 행에 source(공급자) 컬럼 — 같은 테이블에 섞여도 출처 구분
    _append(_part(root, "bronze", "contrail_aircraft", f"source={SOURCE}", ts=ts),
            [_jsonl({"source": SOURCE, **to_aircraft_row(f)}) for f in flights])
    _append(_part(root, "bronze", "contrail_positions", f"source={SOURCE}", ts=ts),
            [_jsonl({"source": SOURCE, **to_position_row(f)}) for f in flights])
    return len(flights)


# ── 수집 ─────────────────────────────────────────────────────────────
async def _fetch(client: httpx.AsyncClient, bbox: tuple | None,
                 state_path: Path | None) -> tuple[dict, dict]:
    started = time.monotonic()
    token = await get_token(client, state_path)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    params = None
    if bbox is not None:  # 전세계는 무파라미터
        lat_min, lon_min, lat_max, lon_max = bbox
        params = {"lamin": lat_min, "lomin": lon_min,
                  "lamax": lat_max, "lomax": lon_max}
    resp = await client.get(STATES_URL, params=params, headers=headers)
    resp.raise_for_status()
    return resp.json(), {
        "bbox": "global" if bbox is None else ",".join(str(v) for v in bbox),
        "status": resp.status_code,
        "elapsed_ms": int((time.monotonic() - started) * 1000)}


async def collect(root: Path, scope: str,
                  transport: httpx.AsyncBaseTransport | None = None) -> int:
    state_path = root / "_state" / "opensky_token.json"
    total = 0
    async with httpx.AsyncClient(timeout=TIMEOUT_S, transport=transport,
                                 headers={"User-Agent": USER_AGENT}) as client:
        if scope in ("global", "both"):
            payload, meta = await _fetch(client, None, state_path)
            land(root, "contrail_global", time.time(), payload, meta, bronze=False)
        if scope in ("regions", "both"):
            for preset, bbox in PRESETS.items():
                await asyncio.sleep(REGION_SPACING_S)
                payload, meta = await _fetch(client, bbox, state_path)
                total += land(root, f"contrail_region_{preset}", time.time(),
                              payload, meta, bronze=True)
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
) -> None:
    """항공 트래픽 1회 수집 → landing + bronze."""
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        asyncio.run(collect(output or DEFAULT_ROOT, scope.value))
    except Exception as exc:
        log.error("실패: %s: %s", type(exc).__name__, exc)
        raise typer.Exit(1)


def main() -> None:
    typer.run(cli)


if __name__ == "__main__":
    main()

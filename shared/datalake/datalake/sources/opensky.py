"""opensky — OpenSky Network 상류. 생산 kind: contrail_global + contrail_region_*.

이식 원본: hub/backend/app/modules/contrail/{auth,normalize}.py. import 금지.
adsblol과 같은 kind를 생산한다 — silver의 contrail_* 테이블은 제공자
중립이고, bronze에서는 source(adsblol/opensky)로 경로가 갈린다.

- OAuth2 client-credentials (DATALAKE_OPENSKY_CLIENT_ID/SECRET), 미설정·발급
  실패 시 익명 감속 모드 (hub 익명 폴백 계약과 동일)
- 토큰은 상태 파일(0600)에 캐시 — one-shot 실행 간 재사용, 만료 60s 전 갱신
- 주의: 데이터센터 IP의 TCP를 드롭하는 사례 실측(2026-08-11, hub가
  adsb.lol로 전환한 이유) — 클라우드 배치에서는 adsblol 권장
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path

import httpx

from ..core.env import env_float, env_str
from ..core.source import Record
from .adsblol import CONTRAIL_PRESETS, USER_AGENT

log = logging.getLogger("datalake.opensky")

STATES_URL = env_str("DATALAKE_OPENSKY_URL",
                     "https://opensky-network.org/api/states/all")
TOKEN_URL = env_str(
    "DATALAKE_OPENSKY_TOKEN_URL",
    "https://auth.opensky-network.org/auth/realms/opensky-network"
    "/protocol/openid-connect/token",
)
CLIENT_ID_ENV = "DATALAKE_OPENSKY_CLIENT_ID"
CLIENT_SECRET_ENV = "DATALAKE_OPENSKY_CLIENT_SECRET"
TIMEOUT_S = env_float("DATALAKE_OPENSKY_TIMEOUT_S", 15.0)
REGION_SPACING_S = 1.1  # 상류 예의 간격 (adsblol과 동일 정책)


# states 인덱스 (OpenSky REST API 계약, hub normalize.py와 동일):
# 0 icao24, 1 callsign, 2 origin_country, 3 time_position, 4 last_contact,
# 5 longitude, 6 latitude, 7 baro_altitude(m), 8 on_ground, 9 velocity(m/s),
# 10 true_track(deg)
def normalize(payload: dict, now: float | None = None) -> list[dict]:
    """states 배열 → contrail 행 (고도·속도는 이미 미터계)."""
    now = time.time() if now is None else now
    out: list[dict] = []
    for s in payload.get("states") or []:
        try:
            icao24, lon, lat = s[0], s[5], s[6]
            if not icao24 or lon is None or lat is None:
                continue
            callsign = (s[1] or "").strip()
            out.append({
                "id": str(icao24),
                "callsign": callsign or None,
                "origin_country": s[2],
                "ts": float(s[3] or s[4] or now),
                "lon": float(lon),
                "lat": float(lat),
                "alt_m": None if s[7] is None else float(s[7]),
                "on_ground": bool(s[8]),
                "velocity_ms": None if s[9] is None else float(s[9]),
                "track_deg": None if s[10] is None else float(s[10]),
                "type": None, "reg": None,  # OpenSky에는 기종·등록부호 없음
            })
        except Exception:  # 한 건의 비정상이 나머지를 죽이지 않음
            log.warning("skipping malformed state entry", exc_info=True)
    return out


class OpenSkyClient:
    id = "opensky"

    def __init__(self, state_path: Path | str | None = None,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._state_path = Path(state_path) if state_path else None
        self._transport = transport

    # ── 토큰 (hub auth.py 이식 + one-shot 상태 파일 캐시) ──────────
    def _read_cached_token(self) -> str | None:
        if self._state_path is None or not self._state_path.exists():
            return None
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            if float(data["expires_at"]) > time.time() + 60:  # 만료 60s 전 갱신
                return str(data["access_token"])
        except Exception:  # 깨진 상태 파일은 무시하고 재발급
            log.warning("opensky token state unreadable", exc_info=True)
        return None

    def _write_token(self, token: str, expires_in: float) -> None:
        if self._state_path is None:
            return
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"access_token": token,
                              "expires_at": time.time() + expires_in})
        # 자격증명 파일은 0600 강제 — umask 기본값(644)의 타 사용자 읽기 차단
        fd = os.open(self._state_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                     0o600)
        try:
            os.write(fd, payload.encode("utf-8"))
        finally:
            os.close(fd)

    async def _get_token(self, client: httpx.AsyncClient) -> str | None:
        client_id = os.environ.get(CLIENT_ID_ENV)
        client_secret = os.environ.get(CLIENT_SECRET_ENV)
        if not client_id or not client_secret:
            return None  # 익명 감속 모드
        cached = self._read_cached_token()
        if cached is not None:
            return cached
        try:
            resp = await client.post(TOKEN_URL, data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            })
            resp.raise_for_status()
            data = resp.json()
            token = str(data["access_token"])
            self._write_token(token, float(data.get("expires_in", 1800)))
            return token
        except Exception as exc:  # 토큰 실패가 수집을 막지 않는다 (hub 동일)
            log.warning("opensky token fetch failed (anonymous fallback): %s", exc)
            return None

    # ── 수집 ────────────────────────────────────────────────────────
    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=TIMEOUT_S, headers={"User-Agent": USER_AGENT},
            transport=self._transport,
        )

    async def _get(self, client: httpx.AsyncClient, bbox: tuple | None,
                   kind: str, bbox_meta: str) -> Record:
        started = time.monotonic()
        token = await self._get_token(client)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        params: dict | None = None
        if bbox is not None:  # 전세계는 무파라미터 (hub fetch_global과 동일)
            lat_min, lon_min, lat_max, lon_max = bbox
            params = {"lamin": lat_min, "lomin": lon_min,
                      "lamax": lat_max, "lomax": lon_max}
        resp = await client.get(STATES_URL, params=params, headers=headers)
        resp.raise_for_status()
        return Record(
            source=self.id,
            kind=kind,
            payload=resp.json(),
            meta={
                "bbox": bbox_meta,
                "status": resp.status_code,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            },
        )

    async def fetch_global(self) -> list[Record]:
        async with self._client() as client:
            return [await self._get(client, None, "contrail_global", "global")]

    async def fetch_regions(self) -> list[Record]:
        records: list[Record] = []
        async with self._client() as client:
            for preset, bbox in CONTRAIL_PRESETS.items():
                await asyncio.sleep(REGION_SPACING_S)
                records.append(await self._get(
                    client, bbox, f"contrail_region_{preset}",
                    ",".join(str(v) for v in bbox),
                ))
        return records


def build(state_path: Path | str | None = None) -> OpenSkyClient:
    return OpenSkyClient(state_path=state_path)

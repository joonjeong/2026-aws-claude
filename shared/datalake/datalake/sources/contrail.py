"""contrail — 항공 트래픽 클라이언트. 제공자 2개: adsb.lol(기본) / OpenSky.

이식 원본: hub/backend/app/modules/contrail/{collector,normalize,auth,config}.py.
import 금지. 권장 스케줄: 전세계 600s + 프리셋 60s (hub adsblol 기본값).

다중 제공자 대응 (설계 §4의 3단 이음새):
- raw 경로: 기본 제공자(adsblol)는 kind=global/region_*, opensky는
  kind=opensky_global/opensky_region_* — 파일이 섞이지 않는다
- meta.provider가 관측 출처 기록
- 정규화는 포맷별 함수(normalize_readsb/normalize_states)가 같은 행으로 수렴
  → model.py 테이블은 제공자 중립 (icao24, ts 키가 겹침 병합)

adsb.lol: 무인증, 원시 URL 조립 필수 (%2C·jv2= 는 400 거부), 순차 1.1s 간격.
OpenSky: OAuth2 client-credentials (없으면 익명 감속 모드), 토큰은 상태
파일에 캐시해 one-shot 실행 간 재사용 (만료 60s 전 갱신 — hub와 동일).
주의: OpenSky는 데이터센터 IP의 TCP를 드롭하는 사례 실측(2026-08-11,
hub가 adsb.lol로 전환한 이유) — 클라우드 배치에서는 adsblol 권장.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

import httpx

from ..core.env import env_float, env_str
from ..core.source import Record

log = logging.getLogger("datalake.contrail")

BASE_URL = env_str("DATALAKE_CONTRAIL_URL", "https://re-api.adsb.lol/")
OPENSKY_URL = env_str("DATALAKE_OPENSKY_URL",
                      "https://opensky-network.org/api/states/all")
OPENSKY_TOKEN_URL = env_str(
    "DATALAKE_OPENSKY_TOKEN_URL",
    "https://auth.opensky-network.org/auth/realms/opensky-network"
    "/protocol/openid-connect/token",
)
OPENSKY_CLIENT_ID_ENV = "DATALAKE_OPENSKY_CLIENT_ID"
OPENSKY_CLIENT_SECRET_ENV = "DATALAKE_OPENSKY_CLIENT_SECRET"

TIMEOUT_S = env_float("DATALAKE_CONTRAIL_TIMEOUT_S", 15.0)
REGION_SPACING_S = 1.1  # 상류 빈도 제한 예의 간격 (hub와 동일)

USER_AGENT = "DataLake/0.1 (+claude-lab; raw archive)"

GLOBAL_BBOX = (-90.0, -180.0, 90.0, 180.0)
# hub contrail config PRESETS 값 복사 — bbox = (lat_min, lon_min, lat_max, lon_max)
PRESETS: dict[str, tuple] = {
    "kr": (30.0, 120.0, 45.0, 135.0),
    "japan": (30.0, 128.0, 43.0, 146.0),
    "europe": (43.0, -5.0, 55.0, 20.0),
    "us-east": (25.0, -90.0, 45.0, -70.0),
}

FT_TO_M = 0.3048
KT_TO_MS = 0.514444


# ── 정규화 (포맷별 → 같은 행으로 수렴, hub normalize.py와 동일) ────────
def normalize_readsb(payload: dict, now: float | None = None) -> list[dict]:
    """adsb.lol re-api (readsb v2) — ft→m, kn→m/s, 항목 격리."""
    now = time.time() if now is None else now
    out: list[dict] = []
    for a in payload.get("ac") or []:
        try:
            hex_id, lat, lon = a["hex"], a.get("lat"), a.get("lon")
            if not hex_id or lat is None or lon is None:
                continue
            alt = a.get("alt_baro")
            on_ground = alt == "ground"
            callsign = (a.get("flight") or "").strip()
            seen_pos = a.get("seen_pos")
            track = a.get("track", a.get("calc_track"))
            gs = a.get("gs")
            out.append({
                "id": str(hex_id),
                "callsign": callsign or None,
                "origin_country": None,  # readsb 응답에는 국가 정보 없음
                "ts": now - float(seen_pos) if seen_pos is not None else now,
                "lon": float(lon),
                "lat": float(lat),
                "alt_m": None if on_ground or alt is None else float(alt) * FT_TO_M,
                "on_ground": on_ground,
                "velocity_ms": None if gs is None else float(gs) * KT_TO_MS,
                "track_deg": None if track is None else float(track),
                "type": a.get("t") or None,
                "reg": a.get("r") or None,
            })
        except Exception:  # 한 건의 비정상이 나머지를 죽이지 않음
            log.warning("skipping malformed ac entry", exc_info=True)
    return out


# states 인덱스 (OpenSky REST API 계약, hub normalize.py와 동일):
# 0 icao24, 1 callsign, 2 origin_country, 3 time_position, 4 last_contact,
# 5 longitude, 6 latitude, 7 baro_altitude(m), 8 on_ground, 9 velocity(m/s),
# 10 true_track(deg)
def normalize_states(payload: dict, now: float | None = None) -> list[dict]:
    """OpenSky states 배열 — 고도·속도는 이미 미터계."""
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


# 기존 소비자(테스트 등) 호환 별칭 — 기본 제공자 포맷
normalize = normalize_readsb


def normalize_for_kind(kind: str, payload: dict,
                       now: float | None = None) -> list[dict]:
    """raw kind로 포맷 판별 — transform이 제공자 무관하게 쓰는 진입점."""
    if kind.startswith("opensky"):
        return normalize_states(payload, now)
    return normalize_readsb(payload, now)


# ── 제공자 ────────────────────────────────────────────────────────────
def box_param(bbox: tuple) -> str:
    """내부 bbox(lat_min, lon_min, lat_max, lon_max) → re-api box 파라미터.

    re-api는 lat_min,lat_max,lon_min,lon_max 순서 (hub box_param과 동일).
    """
    lat_min, lon_min, lat_max, lon_max = bbox
    return f"{lat_min},{lat_max},{lon_min},{lon_max}"


def adsblol_url(base: str, bbox: tuple) -> str:
    return f"{base}?box={box_param(bbox)}&jv2"


class AdsbLolProvider:
    id = "adsblol"

    def kind(self, scope: str) -> str:
        return scope  # 기본 제공자는 무접두 — 기존 raw 경로와 호환

    async def fetch(self, client: httpx.AsyncClient,
                    bbox: tuple | None) -> httpx.Response:
        # 전세계도 bbox로 조회 (re-api에 무파라미터 경로 없음)
        resp = await client.get(adsblol_url(BASE_URL, bbox or GLOBAL_BBOX))
        resp.raise_for_status()
        return resp


class OpenSkyProvider:
    """hub auth.py 이식 + one-shot 대응: 토큰을 상태 파일에 캐시.

    자격증명 미설정·발급 실패 → 익명 진행 (hub의 익명 폴백 계약과 동일).
    """

    id = "opensky"

    def __init__(self, state_path: Path | str | None = None) -> None:
        self._state_path = Path(state_path) if state_path else None

    def kind(self, scope: str) -> str:
        return f"opensky_{scope}"

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
        self._state_path.write_text(
            json.dumps({"access_token": token,
                        "expires_at": time.time() + expires_in}),
            encoding="utf-8",
        )

    async def _get_token(self, client: httpx.AsyncClient) -> str | None:
        import os

        client_id = os.environ.get(OPENSKY_CLIENT_ID_ENV)
        client_secret = os.environ.get(OPENSKY_CLIENT_SECRET_ENV)
        if not client_id or not client_secret:
            return None  # 익명 감속 모드
        cached = self._read_cached_token()
        if cached is not None:
            return cached
        try:
            resp = await client.post(OPENSKY_TOKEN_URL, data={
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

    async def fetch(self, client: httpx.AsyncClient,
                    bbox: tuple | None) -> httpx.Response:
        token = await self._get_token(client)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        params: dict | None = None
        if bbox is not None:  # 전세계는 무파라미터 (hub fetch_global과 동일)
            lat_min, lon_min, lat_max, lon_max = bbox
            params = {"lamin": lat_min, "lomin": lon_min,
                      "lamax": lat_max, "lomax": lon_max}
        resp = await client.get(OPENSKY_URL, params=params, headers=headers)
        resp.raise_for_status()
        return resp


PROVIDERS = {"adsblol": AdsbLolProvider, "opensky": OpenSkyProvider}


# ── 클라이언트 ────────────────────────────────────────────────────────
class ContrailClient:
    id = "contrail"

    def __init__(self, provider=None,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._provider = provider if provider is not None else AdsbLolProvider()
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=TIMEOUT_S, headers={"User-Agent": USER_AGENT},
            transport=self._transport,
        )

    async def _get(self, client: httpx.AsyncClient, bbox: tuple | None,
                   scope: str, bbox_meta: str) -> Record:
        started = time.monotonic()
        resp = await self._provider.fetch(client, bbox)
        return Record(
            source=self.id,
            kind=self._provider.kind(scope),
            payload=resp.json(),
            meta={
                "provider": self._provider.id,
                "bbox": bbox_meta,
                "status": resp.status_code,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            },
        )

    async def fetch_global(self) -> list[Record]:
        async with self._client() as client:
            bbox = GLOBAL_BBOX if self._provider.id == "adsblol" else None
            return [await self._get(client, bbox, "global", "global")]

    async def fetch_regions(self) -> list[Record]:
        records: list[Record] = []
        async with self._client() as client:
            for preset, bbox in PRESETS.items():
                await asyncio.sleep(REGION_SPACING_S)  # 빈도 제한 예의 간격
                records.append(await self._get(
                    client, bbox, f"region_{preset}",
                    ",".join(str(v) for v in bbox),
                ))
        return records


def build(provider: str | None = None,
          state_path: Path | str | None = None) -> ContrailClient:
    name = provider or env_str("DATALAKE_CONTRAIL_PROVIDER", "adsblol")
    if name not in PROVIDERS:
        raise ValueError(f"알 수 없는 제공자: {name} ({list(PROVIDERS)})")
    if name == "opensky":
        return ContrailClient(provider=OpenSkyProvider(state_path=state_path))
    return ContrailClient(provider=AdsbLolProvider())

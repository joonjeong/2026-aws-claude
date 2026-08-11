"""adsblol — adsb.lol re-api 상류. 생산 kind: contrail_global + contrail_region_*.

이식 원본: hub/backend/app/modules/contrail/{collector,normalize,config}.py. import 금지.
한 상류가 여러 데이터셋(kind)을 생산하는 대표 사례 — 명령 하나
(datalake-adsblol)가 전세계 1개 + 프리셋 4개 kind를 만든다.

- 원시 URL 조립 필수: re-api는 %2C(콤마 인코딩)·jv2=(등호) 모두 400 거부
- 프리셋 조회는 순차 1.1s 간격 (병렬 4요청 → 420, hub 실측)
- 권장 스케줄: regions 60s / global 600s (hub adsblol 기본값)

CONTRAIL_PRESETS·정규화 행 계약은 opensky 상류와 공유 — 두 상류가 silver의
같은 contrail_* 테이블로 수렴한다 (model.py는 제공자 중립).
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

from ..core.env import env_float, env_str
from ..core.source import Record

log = logging.getLogger("datalake.adsblol")

BASE_URL = env_str("DATALAKE_ADSBLOL_URL", "https://re-api.adsb.lol/")
TIMEOUT_S = env_float("DATALAKE_ADSBLOL_TIMEOUT_S", 15.0)
REGION_SPACING_S = 1.1  # re-api 빈도 제한 예의 간격 (hub와 동일)

USER_AGENT = "DataLake/0.1 (+claude-lab; raw archive)"

GLOBAL_BBOX = (-90.0, -180.0, 90.0, 180.0)
# hub contrail config PRESETS 값 복사 — bbox = (lat_min, lon_min, lat_max, lon_max)
# opensky.py도 이 정의를 공유한다 (contrail 도메인 공통)
CONTRAIL_PRESETS: dict[str, tuple] = {
    "kr": (30.0, 120.0, 45.0, 135.0),
    "japan": (30.0, 128.0, 43.0, 146.0),
    "europe": (43.0, -5.0, 55.0, 20.0),
    "us-east": (25.0, -90.0, 45.0, -70.0),
}

FT_TO_M = 0.3048
KT_TO_MS = 0.514444


def normalize(payload: dict, now: float | None = None) -> list[dict]:
    """readsb v2 → contrail 행 (ft→m, kn→m/s, 항목 격리 — hub와 동일)."""
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


def box_param(bbox: tuple) -> str:
    """내부 bbox(lat_min, lon_min, lat_max, lon_max) → re-api box 파라미터.

    re-api는 lat_min,lat_max,lon_min,lon_max 순서 (hub box_param과 동일).
    """
    lat_min, lon_min, lat_max, lon_max = bbox
    return f"{lat_min},{lat_max},{lon_min},{lon_max}"


def adsblol_url(base: str, bbox: tuple) -> str:
    return f"{base}?box={box_param(bbox)}&jv2"


class AdsbLolClient:
    id = "adsblol"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=TIMEOUT_S, headers={"User-Agent": USER_AGENT},
            transport=self._transport,
        )

    async def _get(self, client: httpx.AsyncClient, bbox: tuple,
                   kind: str, bbox_meta: str) -> Record:
        started = time.monotonic()
        resp = await client.get(adsblol_url(BASE_URL, bbox))
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
            return [await self._get(client, GLOBAL_BBOX,
                                    "contrail_global", "global")]

    async def fetch_regions(self) -> list[Record]:
        records: list[Record] = []
        async with self._client() as client:
            for preset, bbox in CONTRAIL_PRESETS.items():
                await asyncio.sleep(REGION_SPACING_S)  # 빈도 제한 예의 간격
                records.append(await self._get(
                    client, bbox, f"contrail_region_{preset}",
                    ",".join(str(v) for v in bbox),
                ))
        return records


def build() -> AdsbLolClient:
    return AdsbLolClient()

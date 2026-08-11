"""wake — AISStream WebSocket 해상 트래픽. hub wake 모듈과 동일 구독·정규화.

이식 원본: hub/backend/app/modules/wake/{collector,config}.py. import 금지.

- hub와 키 공유 금지: AISStream은 키당 동시 연결 제한 — 전용 DATALAKE_AIS_KEY
  필수, 미설정 시 build()가 None (hub의 no_key 저하 계약과 동형, 설계 §7.1)
- parse는 bbox 필터·정규화 없이 메시지 원본을 통짜 저장 (레이크 = 원본 보존).
  normalize_position/static은 SQLite 싱크용.
"""

from __future__ import annotations

import logging
import os

from labkit.config import env_str

from ..core.source import Record

log = logging.getLogger("datalake.wake")

STREAM_URL = env_str("DATALAKE_AIS_URL", "wss://stream.aisstream.io/v0/stream")
KEY_ENV = "DATALAKE_AIS_KEY"

# hub wake config PRESETS 값 복사 — bbox = (lat_min, lon_min, lat_max, lon_max)
PRESETS: dict[str, tuple] = {
    "kr": (30.0, 120.0, 45.0, 135.0),
    "taiwan": (20.0, 115.0, 28.0, 125.0),
    "sea": (-10.0, 95.0, 15.0, 120.0),
}
DEFAULT_PRESET = env_str("DATALAKE_WAKE_PRESET", "kr")  # hub WAKE_DEFAULT_PRESET


def ship_type_label(code) -> str:
    """AIS ship type code → 대분류 (ITU-R M.1371, hub와 동일)."""
    try:
        code = int(code)
    except (TypeError, ValueError):
        return "기타"
    if code == 30:
        return "어선"
    if 60 <= code <= 69:
        return "여객"
    if 70 <= code <= 79:
        return "화물"
    if 80 <= code <= 89:
        return "탱커"
    return "기타"


def _clean_name(raw) -> str | None:
    name = str(raw).strip() if raw else ""
    return name or None


def normalize_position(msg: dict, now: float) -> dict | None:
    """AIS 특수값: Sog 102.3 / Cog 360 / TrueHeading 511 = '없음' → None."""
    meta = msg.get("MetaData") or {}
    body = ((msg.get("Message") or {}).get("PositionReport")) or {}
    mmsi = meta.get("MMSI")
    lat, lon = body.get("Latitude"), body.get("Longitude")
    if mmsi is None or lat is None or lon is None:
        return None
    sog, cog, heading = body.get("Sog"), body.get("Cog"), body.get("TrueHeading")
    return {
        "id": str(mmsi),
        "ts": now,
        "lon": float(lon),
        "lat": float(lat),
        "sog_kn": None if sog in (None, 102.3) else float(sog),
        "cog_deg": None if cog in (None, 360.0) else float(cog),
        "heading_deg": None if heading in (None, 511) else float(heading),
        "name": _clean_name(meta.get("ShipName")),
    }


def normalize_static(msg: dict) -> tuple[str, dict] | None:
    meta = msg.get("MetaData") or {}
    body = ((msg.get("Message") or {}).get("ShipStaticData")) or {}
    mmsi = meta.get("MMSI")
    if mmsi is None:
        return None
    return str(mmsi), {
        "name": _clean_name(body.get("Name")),
        "ship_type": ship_type_label(body.get("Type")),
        "callsign": _clean_name(body.get("CallSign")),
    }


class WakeSource:
    id = "wake"
    url = STREAM_URL

    def __init__(self, api_key: str, preset: str | None = None) -> None:
        self._api_key = api_key
        self._preset = preset or DEFAULT_PRESET
        if self._preset not in PRESETS:
            raise ValueError(f"알 수 없는 프리셋: {self._preset} ({list(PRESETS)})")

    def subscribe_payload(self) -> dict:
        lat_min, lon_min, lat_max, lon_max = PRESETS[self._preset]
        return {
            "APIKey": self._api_key,
            "BoundingBoxes": [[[lat_min, lon_min], [lat_max, lon_max]]],
            "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
        }

    def parse(self, msg) -> list[Record]:
        if not isinstance(msg, dict):
            log.warning("non-dict AIS message skipped: %s", type(msg).__name__)
            return []
        return [Record(source=self.id, kind="ais", payload=msg,
                       meta={"preset": self._preset})]


def build() -> WakeSource | None:
    api_key = os.environ.get(KEY_ENV)
    if not api_key:
        log.info("wake 비활성: %s 미설정 (hub 키 공유 금지 — 전용 키 필요)", KEY_ENV)
        return None
    return WakeSource(api_key=api_key)

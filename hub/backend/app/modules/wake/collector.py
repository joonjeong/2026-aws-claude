"""AISStream collector: labkit StreamCollector + 메시지 정규화.

PositionReport → TrailStore.ingest → (trail 수용분 중 게이트 통과분만) fact 기록.
ShipStaticData → 개체 메타 병합 + dim 갱신. 건별 격리는 StreamCollector가 보장.
"""
from __future__ import annotations

import logging
import time

from labkit import StreamCollector

from ...archive import archive_insert
from . import config, schema
from .store import store

logger = logging.getLogger(__name__)

# AIS ship type code → 대분류 (ITU-R M.1371 2자리 코드)
def ship_type_label(code) -> str:
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


def _in_bbox(lat: float, lon: float, bbox: tuple) -> bool:
    lat_min, lon_min, lat_max, lon_max = bbox
    return lat_min <= lat <= lat_max and lon_min <= lon <= lon_max


def handle_message(msg: dict) -> None:
    mtype = msg.get("MessageType")
    if mtype == "PositionReport":
        point = normalize_position(msg, time.time())
        if point is None:
            return
        if not _in_bbox(point["lat"], point["lon"], store.preset()["bbox"]):
            return  # 구독 전환 경합: 새 bbox 적용 전 대기 중이던 메시지
        added = store.trails.ingest(point)
        if added:  # dim·fact 기록은 trail 수용분만 — 메시지 폭주가 DB에 닿지 않게
            archive_insert(schema.UPSERT_VESSEL, [(
                point["id"], point["name"], None, None, point["ts"], point["ts"],
            )])
            if store.should_archive(point["id"], point["ts"]):
                archive_insert(schema.INSERT_POSITION, [(
                    point["id"], point["ts"], point["lon"], point["lat"],
                    point["sog_kn"], point["cog_deg"], point["heading_deg"],
                )])
    elif mtype == "ShipStaticData":
        parsed = normalize_static(msg)
        if parsed is None:
            return
        mmsi, meta = parsed
        store.trails.merge_meta(mmsi, meta)
        now = time.time()
        archive_insert(schema.UPSERT_VESSEL, [(
            mmsi, meta["name"], meta["ship_type"], meta["callsign"], now, now,
        )])


def _subscribe() -> dict:
    lat_min, lon_min, lat_max, lon_max = store.preset()["bbox"]
    return {
        "APIKey": config.AIS_KEY,
        "BoundingBoxes": [[[lat_min, lon_min], [lat_max, lon_max]]],
        "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
    }


collector = StreamCollector(
    name="wake-ais",
    url=config.AIS_URL,
    on_message=handle_message,
    subscribe=_subscribe,
)

"""수집 응답 정규화 — OpenSky states 배열, adsb.lol re-api(readsb v2) ac 배열."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# states 인덱스 (OpenSky REST API 계약):
# 0 icao24, 1 callsign, 2 origin_country, 3 time_position, 4 last_contact,
# 5 longitude, 6 latitude, 7 baro_altitude(m), 8 on_ground, 9 velocity(m/s),
# 10 true_track(deg)


def normalize_states(payload: dict, now: float) -> list[dict]:
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
            logger.warning("skipping malformed state entry", exc_info=True)
    return out


FT_TO_M = 0.3048
KT_TO_MS = 0.514444

# readsb v2 필드: hex, flight(콜사인), lat/lon, alt_baro(ft 또는 "ground"),
# gs(knots), track(deg, 없으면 calc_track), seen_pos(마지막 위치 후 경과초)


def normalize_readsb(payload: dict, now: float) -> list[dict]:
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
            logger.warning("skipping malformed ac entry", exc_info=True)
    return out

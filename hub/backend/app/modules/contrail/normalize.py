"""OpenSky /states/all 응답 정규화 — 인덱스 기반 states 배열을 dict로."""
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
            })
        except Exception:  # 한 건의 비정상이 나머지를 죽이지 않음
            logger.warning("skipping malformed state entry", exc_info=True)
    return out

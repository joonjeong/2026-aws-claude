"""raw Record → 정규화 테이블 행 변환 (datalake/model.py 스펙과 짝).

각 소스의 normalize()를 호출해 테이블별 행 dict를 만든다. SQLite 시절
싱크 핸들러의 후신 — 이제 저장 형식(Parquet)과 분리된 순수 변환이다.
"""

from __future__ import annotations

import logging

from .source import Record

log = logging.getLogger("datalake.transform")

TREND_BUCKET_S = 60.0  # hub POLL_INTERVAL_S — ts 버킷 정렬값 (재구축 멱등)


def _quake(r: Record) -> dict[str, list[dict]]:
    from ..sources.quake import normalize

    return {"quake_events": normalize(r.payload)}


def _news(r: Record) -> dict[str, list[dict]]:
    from ..sources.news import normalize

    return {"news_articles": [
        {**a, "first_seen": r.fetched_at}
        for a in normalize(r.kind, r.payload)
    ]}


def _trend(r: Record) -> dict[str, list[dict]]:
    from ..sources.trend import normalize

    items = normalize(r.payload)
    ts = float(int(r.fetched_at // TREND_BUCKET_S) * TREND_BUCKET_S)
    return {
        "trend_videos": [
            {"video_id": i["video_id"], "title": i["title"],
             "channel": i["channel"], "category_id": i["category_id"],
             "thumbnail": i["thumbnail"], "published_at": i["published_at"],
             "first_seen": r.fetched_at, "last_seen": r.fetched_at}
            for i in items
        ],
        "trend_video_stats": [
            {"video_id": i["video_id"], "ts": ts, "rank": rank,
             "view_count": i["view_count"], "like_count": i["like_count"]}
            for rank, i in enumerate(items, start=1)
        ],
    }


def _contrail(r: Record) -> dict[str, list[dict]]:
    from ..sources.contrail import normalize_for_kind

    if r.kind.endswith("global"):
        return {}  # hub와 동일 — 전세계 스냅샷은 정규화 존 제외 (홍수 방지)
    # 제공자별 포맷(readsb/states)은 kind 접두사로 디스패치 — 같은 행으로 수렴
    flights = normalize_for_kind(r.kind, r.payload, now=r.fetched_at)
    return {
        "contrail_aircraft": [
            {"icao24": f["id"], "callsign": f["callsign"],
             "origin_country": f["origin_country"],
             "first_seen": f["ts"], "last_seen": f["ts"]}
            for f in flights
        ],
        "contrail_positions": [
            {"icao24": f["id"], "ts": f["ts"], "lon": f["lon"], "lat": f["lat"],
             "alt_m": f["alt_m"], "velocity_ms": f["velocity_ms"],
             "track_deg": f["track_deg"], "on_ground": f["on_ground"]}
            for f in flights
        ],
    }


def _wake(r: Record) -> dict[str, list[dict]]:
    from ..sources.wake import normalize_position, normalize_static

    msg = r.payload
    mtype = msg.get("MessageType")
    if mtype == "PositionReport":
        point = normalize_position(msg, now=r.fetched_at)
        if point is None:
            return {}
        return {
            "wake_vessels": [
                {"mmsi": point["id"], "name": point["name"], "ship_type": None,
                 "callsign": None, "first_seen": point["ts"],
                 "last_seen": point["ts"]},
            ],
            "wake_positions": [
                {"mmsi": point["id"], "ts": point["ts"], "lon": point["lon"],
                 "lat": point["lat"], "sog_kn": point["sog_kn"],
                 "cog_deg": point["cog_deg"],
                 "heading_deg": point["heading_deg"]},
            ],
        }
    if mtype == "ShipStaticData":
        parsed = normalize_static(msg)
        if parsed is None:
            return {}
        mmsi, meta = parsed
        return {"wake_vessels": [
            {"mmsi": mmsi, "name": meta["name"], "ship_type": meta["ship_type"],
             "callsign": meta["callsign"], "first_seen": r.fetched_at,
             "last_seen": r.fetched_at},
        ]}
    return {}


def _flashpoint(r: Record) -> dict[str, list[dict]]:
    # raw는 필터 전 CSV 전문 — 여기서 hub 동형 필터(CAMEO 루트 14~20) 적용
    from ..sources.flashpoint import normalize

    return {"flashpoint_events": normalize(r.payload)}


def _market(r: Record) -> dict[str, list[dict]]:
    def row(q: dict, kind: str, market: str | None) -> dict:
        return {"ts": r.fetched_at, "kind": kind, "symbol": q.get("symbol"),
                "name": q.get("name"), "price": q.get("price"),
                "change": q.get("change"), "change_pct": q.get("change_pct"),
                "volume": q.get("volume"), "market": market}

    rows: list[dict] = []
    if r.kind == "overview":
        for q in r.payload.get("indices") or []:
            rows.append(row(q, "index", q.get("market")))
        for q in r.payload.get("indicators") or []:
            rows.append(row(q, "indicator", None))
    elif r.kind == "quotes_us":
        rows = [row(q, "quote_us", "US") for q in r.payload or []]
    elif r.kind == "quotes_kr":
        rows = [row(q, "quote_kr", "KR") for q in r.payload or []]
    return {"market_quotes": rows}


_HANDLERS = {
    "quake": _quake,
    "news": _news,
    "trend": _trend,
    "contrail": _contrail,
    "wake": _wake,
    "flashpoint": _flashpoint,
    "market": _market,
}


def rows_for(record: Record) -> dict[str, list[dict]]:
    """Record → {table: rows}. 미지 소스·깨진 레코드는 빈 dict (건별 격리)."""
    handler = _HANDLERS.get(record.source)
    if handler is None:
        return {}
    try:
        return handler(record)
    except Exception:
        log.exception("transform failed: %s/%s", record.source, record.kind)
        return {}

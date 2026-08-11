"""bronze Record → silver 테이블 행 변환 (datalake/model.py 스펙과 짝).

디스패치 축은 source(상류) — 상류가 포맷을 결정하므로 정규화 함수도
상류별이다. kind(데이터셋)는 같은 상류 안의 스트림 구분에 쓰인다
(예: adsblol의 contrail_global/contrail_region_*).
"""

from __future__ import annotations

import logging

from .source import Record

log = logging.getLogger("datalake.transform")

TREND_BUCKET_S = 60.0  # hub POLL_INTERVAL_S — ts 버킷 정렬값 (재구축 멱등)


def _usgs_feed(r: Record) -> dict[str, list[dict]]:
    from ..sources.usgs_feed import normalize

    return {"quake_events": normalize(r.payload)}


def _rss(r: Record) -> dict[str, list[dict]]:
    from ..sources.rss import normalize

    # 매체 id = record.source (상류가 곧 매체)
    return {"news_articles": [
        {**a, "first_seen": r.fetched_at}
        for a in normalize(r.source, r.payload)
    ]}


def _youtube(r: Record) -> dict[str, list[dict]]:
    from ..sources.youtube import normalize

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
    # 상류(source)가 포맷을 결정: adsblol=readsb v2, opensky=states 배열.
    # 두 상류가 같은 제공자 중립 테이블로 수렴한다.
    if r.kind == "contrail_global":
        return {}  # hub와 동일 — 전세계 스냅샷은 silver 제외 (홍수 방지)
    if r.source == "opensky":
        from ..sources.opensky import normalize
    else:
        from ..sources.adsblol import normalize
    flights = normalize(r.payload, now=r.fetched_at)
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


def _aisstream(r: Record) -> dict[str, list[dict]]:
    from ..sources.aisstream import normalize_position, normalize_static

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


def _gdelt(r: Record) -> dict[str, list[dict]]:
    # bronze는 필터 전 CSV 전문 — 여기서 hub 동형 필터(CAMEO 루트 14~20) 적용
    from ..sources.gdelt import normalize

    return {"flashpoint_events": normalize(r.payload)}


def _market_row(r: Record, q: dict, kind: str, market: str | None) -> dict:
    return {"ts": r.fetched_at, "kind": kind, "symbol": q.get("symbol"),
            "name": q.get("name"), "price": q.get("price"),
            "change": q.get("change"), "change_pct": q.get("change_pct"),
            "volume": q.get("volume"), "market": market}


def _yfinance(r: Record) -> dict[str, list[dict]]:
    rows: list[dict] = []
    if r.kind == "market_overview":
        for q in r.payload.get("indices") or []:
            rows.append(_market_row(r, q, "index", q.get("market")))
        for q in r.payload.get("indicators") or []:
            rows.append(_market_row(r, q, "indicator", None))
    elif r.kind == "market_quotes_us":
        rows = [_market_row(r, q, "quote_us", "US") for q in r.payload or []]
    return {"market_quotes": rows}


def _pykrx(r: Record) -> dict[str, list[dict]]:
    return {"market_quotes": [
        _market_row(r, q, "quote_kr", "KR") for q in r.payload or []
    ]}


def _handler_for(source: str):
    if source == "usgs_feed":
        return _usgs_feed
    from ..sources.rss import FEEDS

    if source in FEEDS:
        return _rss
    return {
        "youtube": _youtube,
        "adsblol": _contrail,
        "opensky": _contrail,
        "aisstream": _aisstream,
        "gdelt": _gdelt,
        "yfinance": _yfinance,
        "pykrx": _pykrx,
    }.get(source)


def rows_for(record: Record) -> dict[str, list[dict]]:
    """Record → {table: rows}. 미지 소스·깨진 레코드는 빈 dict (건별 격리)."""
    handler = _handler_for(record.source)
    if handler is None:
        return {}
    try:
        return handler(record)
    except Exception:
        log.exception("transform failed: %s/%s", record.source, record.kind)
        return {}

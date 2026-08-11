"""정규화 존 데이터 모델 — 테이블 스펙의 단일 진실 (pyarrow 스키마).

Parquet 파일에 스키마가 내장되므로 소비자(DuckDB·Postgres FDW·pandas)는
이 파일 없이도 타입을 안다. 여기는 생성 측 계약: 컬럼·타입·키·병합 규칙.

레이아웃: <ROOT>/normalized/<table>/dt=YYYY-MM-DD/part-000.parquet
- 파티션 의미: "그 날짜(UTC)에 **관측**된 행" — raw의 fetched_at 기준.
  같은 자연키가 여러 날짜에 걸쳐 나타날 수 있다 (예: quake 2.5_day 피드).
  전역 유일이 필요하면 소비 측에서 키로 dedup (SELECT DISTINCT ON ...).
- 파티션 내 dedup은 생성 시 키로 수행: merge=False는 최초 관측 유지,
  merge=True(dim류)는 후속 관측의 non-null 필드가 갱신하되
  first_seen=min / last_seen=max (hub의 COALESCE 업서트와 동형).
"""

from __future__ import annotations

from dataclasses import dataclass

import pyarrow as pa


@dataclass(frozen=True)
class TableSpec:
    name: str
    schema: pa.Schema
    key: tuple[str, ...]
    merge: bool  # True = dim류 병합, False = 최초 관측 유지


SPECS: dict[str, TableSpec] = {
    "quake_events": TableSpec(
        name="quake_events",
        schema=pa.schema([
            ("id", pa.string()),
            ("mag", pa.float64()),
            ("place", pa.string()),
            ("time", pa.int64()),       # epoch ms (USGS 원본 단위)
            ("lon", pa.float64()),
            ("lat", pa.float64()),
            ("depth_km", pa.float64()),
        ]),
        key=("id",),
        merge=False,
    ),
    "news_articles": TableSpec(
        name="news_articles",
        schema=pa.schema([
            ("link", pa.string()),
            ("source", pa.string()),
            ("title", pa.string()),
            ("published", pa.string()),  # ISO-8601 Z
            ("summary", pa.string()),
            ("first_seen", pa.float64()),  # epoch s
        ]),
        key=("link",),
        merge=False,
    ),
    "trend_videos": TableSpec(
        name="trend_videos",
        schema=pa.schema([
            ("video_id", pa.string()),
            ("title", pa.string()),
            ("channel", pa.string()),
            ("category_id", pa.string()),
            ("thumbnail", pa.string()),
            ("published_at", pa.string()),
            ("first_seen", pa.float64()),
            ("last_seen", pa.float64()),
        ]),
        key=("video_id",),
        merge=True,
    ),
    "trend_video_stats": TableSpec(
        name="trend_video_stats",
        schema=pa.schema([
            ("video_id", pa.string()),
            ("ts", pa.float64()),        # 60s 버킷 정렬값 (hub와 동형)
            ("rank", pa.int32()),
            ("view_count", pa.int64()),
            ("like_count", pa.int64()),
        ]),
        key=("video_id", "ts"),
        merge=False,
    ),
    "contrail_aircraft": TableSpec(
        name="contrail_aircraft",
        schema=pa.schema([
            ("icao24", pa.string()),
            ("callsign", pa.string()),
            ("origin_country", pa.string()),
            ("first_seen", pa.float64()),
            ("last_seen", pa.float64()),
        ]),
        key=("icao24",),
        merge=True,
    ),
    "contrail_positions": TableSpec(
        name="contrail_positions",
        schema=pa.schema([
            ("icao24", pa.string()),
            ("ts", pa.float64()),
            ("lon", pa.float64()),
            ("lat", pa.float64()),
            ("alt_m", pa.float64()),
            ("velocity_ms", pa.float64()),
            ("track_deg", pa.float64()),
            ("on_ground", pa.bool_()),
        ]),
        key=("icao24", "ts"),
        merge=False,
    ),
    "wake_vessels": TableSpec(
        name="wake_vessels",
        schema=pa.schema([
            ("mmsi", pa.string()),
            ("name", pa.string()),
            ("ship_type", pa.string()),
            ("callsign", pa.string()),
            ("first_seen", pa.float64()),
            ("last_seen", pa.float64()),
        ]),
        key=("mmsi",),
        merge=True,
    ),
    "wake_positions": TableSpec(
        name="wake_positions",
        schema=pa.schema([
            ("mmsi", pa.string()),
            ("ts", pa.float64()),
            ("lon", pa.float64()),
            ("lat", pa.float64()),
            ("sog_kn", pa.float64()),
            ("cog_deg", pa.float64()),
            ("heading_deg", pa.float64()),
        ]),
        key=("mmsi", "ts"),
        merge=False,
    ),
    "flashpoint_events": TableSpec(
        name="flashpoint_events",
        schema=pa.schema([
            ("event_id", pa.int64()),
            ("ts", pa.float64()),
            ("event_day", pa.string()),   # YYYYMMDD
            ("code", pa.string()),        # CAMEO event code
            ("root", pa.string()),        # CAMEO root (14~20 필터, hub 동형)
            ("quad", pa.int32()),
            ("goldstein", pa.float64()),
            ("mentions", pa.int64()),
            ("articles", pa.int64()),
            ("tone", pa.float64()),
            ("actor1", pa.string()),
            ("actor2", pa.string()),
            ("lat", pa.float64()),
            ("lon", pa.float64()),
            ("country", pa.string()),
            ("source_url", pa.string()),
        ]),
        key=("event_id",),
        merge=False,
    ),
    # hub는 market을 JSON snapshots로 두지만, 정규화 존은 평탄화한다 —
    # kind: index(지수, market 컬럼) / indicator(지표) / quote_us / quote_kr
    "market_quotes": TableSpec(
        name="market_quotes",
        schema=pa.schema([
            ("ts", pa.float64()),        # fetched_at
            ("kind", pa.string()),
            ("symbol", pa.string()),
            ("name", pa.string()),
            ("price", pa.float64()),
            ("change", pa.float64()),
            ("change_pct", pa.float64()),
            ("volume", pa.int64()),
            ("market", pa.string()),     # US/KR (index·quote), indicator는 null
        ]),
        key=("kind", "symbol", "ts"),
        merge=False,
    ),
}

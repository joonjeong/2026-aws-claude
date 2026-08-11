"""정규화 존 — model 스펙·transform·Parquet 물질화(materialize) 검증."""

from datetime import datetime, timezone

import pyarrow.parquet as pq

from datalake import model
from datalake.core.parquet import materialize
from datalake.core.sinks import FileSink
from datalake.core.source import Record
from datalake.core.transform import rows_for

TS = datetime(2026, 8, 11, 6, 30, tzinfo=timezone.utc).timestamp()
DT = "2026-08-11"


def _quake_rec(ts=TS):
    return Record(
        source="usgs_feed", kind="quake", fetched_at=ts, meta={},
        payload={"features": [{
            "id": "us100",
            "properties": {"mag": 4.5, "place": "Korea", "time": 1786430000000},
            "geometry": {"coordinates": [127.0, 37.5, 10.0]},
        }]},
    )


def _market_rec():
    return Record(
        source="yfinance", kind="market_overview", fetched_at=TS, meta={},
        payload={
            "indices": [{"symbol": "^KS11", "name": "KOSPI", "price": 3000.0,
                         "change": 10.0, "change_pct": 0.33, "volume": 0,
                         "market": "KR"}],
            "indicators": [{"symbol": "BTC-USD", "name": "비트코인",
                            "price": 100000.0, "change": -5.0,
                            "change_pct": -0.01, "volume": 123}],
        },
    )


def _wake_recs():
    pos = Record(
        source="aisstream", kind="wake", fetched_at=TS, meta={"preset": "kr"},
        payload={"MessageType": "PositionReport",
                 "MetaData": {"MMSI": 440000001, "ShipName": "HANARA"},
                 "Message": {"PositionReport": {
                     "Latitude": 36.0, "Longitude": 129.0,
                     "Sog": 12.3, "Cog": 90.0, "TrueHeading": 91}}},
    )
    static = Record(
        source="aisstream", kind="wake", fetched_at=TS + 60, meta={"preset": "kr"},
        payload={"MessageType": "ShipStaticData",
                 "MetaData": {"MMSI": 440000001},
                 "Message": {"ShipStaticData": {"Name": "HANARA", "Type": 70,
                                                "CallSign": "AB1"}}},
    )
    return [pos, static]


def test_every_transform_table_has_spec():
    for rec in [_quake_rec(), _market_rec(), *_wake_recs()]:
        for table, rows in rows_for(rec).items():
            spec = model.SPECS[table]  # KeyError면 모델 스펙 누락
            for row in rows:
                unknown = set(row) - set(spec.schema.names)
                assert not unknown, f"{table}: 스펙에 없는 컬럼 {unknown}"


def test_market_flattening():
    rows = rows_for(_market_rec())["market_quotes"]
    kinds = {(r["kind"], r["symbol"], r["market"]) for r in rows}
    assert kinds == {("index", "^KS11", "KR"), ("indicator", "BTC-USD", None)}


def test_materialize_partition_idempotent(tmp_path):
    sink = FileSink(tmp_path)
    # 같은 quake 이벤트가 두 사이클에 걸쳐 관측 + wake 2종 + market
    sink.write([_quake_rec(), _quake_rec(ts=TS + 60), _market_rec(),
                *_wake_recs()])

    counts = materialize(tmp_path, DT)
    assert counts["quake_events"] == 1        # 파티션 내 키 dedup (최초 관측)
    assert counts["market_quotes"] == 2
    assert counts["wake_vessels"] == 1        # dim 병합
    assert counts["wake_positions"] == 1

    # dim 병합: static의 non-null이 갱신, first/last_seen은 min/max
    vessels = pq.read_table(
        tmp_path / "silver/wake_vessels/dt=2026-08-11/part-000.parquet")
    (row,) = vessels.to_pylist()
    assert row["ship_type"] == "화물" and row["callsign"] == "AB1"
    assert row["name"] == "HANARA"
    assert row["first_seen"] == TS and row["last_seen"] == TS + 60

    # 스키마는 model 스펙과 동일 (파일 내장)
    quake_t = pq.read_table(
        tmp_path / "silver/quake_events/dt=2026-08-11/part-000.parquet")
    assert quake_t.schema.equals(model.SPECS["quake_events"].schema)

    # 재실행 = 파티션 재작성 = 멱등
    assert materialize(tmp_path, DT) == counts


def test_materialize_date_filter(tmp_path):
    other_day = datetime(2026, 8, 10, 6, 0, tzinfo=timezone.utc).timestamp()
    FileSink(tmp_path).write([_quake_rec(), _quake_rec(ts=other_day)])

    counts = materialize(tmp_path, DT)
    assert counts["quake_events"] == 1
    assert not (tmp_path / "silver/quake_events/dt=2026-08-10").exists()

    counts_prev = materialize(tmp_path, "2026-08-10")
    assert counts_prev["quake_events"] == 1


def test_materialize_tables_filter(tmp_path):
    FileSink(tmp_path).write([_quake_rec(), _market_rec()])
    counts = materialize(tmp_path, DT, tables={"market_quotes"})
    assert set(counts) == {"market_quotes"}
    assert not (tmp_path / "silver/quake_events").exists()

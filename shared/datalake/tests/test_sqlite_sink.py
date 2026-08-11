import json
from datetime import datetime, timezone

from datalake.core.sinks import FileSink
from datalake.core.source import Record
from datalake.core.sqlite_sink import SqliteSink

TS = datetime(2026, 8, 11, 6, 30, tzinfo=timezone.utc).timestamp()


def _quake_rec():
    return Record(
        source="quake", kind="usgs_feed", fetched_at=TS, meta={},
        payload={"features": [{
            "id": "us100",
            "properties": {"mag": 4.5, "place": "Korea", "time": 1786430000000},
            "geometry": {"coordinates": [127.0, 37.5, 10.0]},
        }]},
    )


def _news_rec():
    xml = """<?xml version="1.0"?><rss version="2.0"><channel>
      <item><link>https://ex.com/a</link><title>Hello</title>
      <pubDate>Mon, 10 Aug 2026 01:00:00 GMT</pubDate>
      <description>Sum</description></item></channel></rss>"""
    return Record(source="news", kind="bbc", payload=xml, meta={}, fetched_at=TS)


def _trend_rec():
    return Record(
        source="trend", kind="trending", fetched_at=TS, meta={},
        payload={"items": [
            {"id": "v1", "snippet": {"title": "T", "channelTitle": "C",
                                     "categoryId": "10", "thumbnails": {},
                                     "publishedAt": "p"},
             "statistics": {"viewCount": "100", "likeCount": "5"}},
            {"id": "v2", "snippet": {"title": "T2", "channelTitle": "C2",
                                     "categoryId": "24", "thumbnails": {},
                                     "publishedAt": "p"},
             "statistics": {"viewCount": "50", "likeCount": "1"}},
        ]},
    )


def _contrail_rec(kind="region_kr"):
    return Record(
        source="contrail", kind=kind, fetched_at=TS, meta={},
        payload={"ac": [{"hex": "abc", "flight": "KAL1", "lat": 37.0,
                         "lon": 127.0, "alt_baro": 10000, "gs": 400,
                         "track": 90, "seen_pos": 0.0}]},
    )


def _wake_pos_rec():
    return Record(
        source="wake", kind="ais", fetched_at=TS, meta={"preset": "kr"},
        payload={"MessageType": "PositionReport",
                 "MetaData": {"MMSI": 440000001, "ShipName": "HANARA"},
                 "Message": {"PositionReport": {
                     "Latitude": 36.0, "Longitude": 129.0,
                     "Sog": 12.3, "Cog": 90.0, "TrueHeading": 91}}},
    )


def _wake_static_rec():
    return Record(
        source="wake", kind="ais", fetched_at=TS, meta={"preset": "kr"},
        payload={"MessageType": "ShipStaticData",
                 "MetaData": {"MMSI": 440000001},
                 "Message": {"ShipStaticData": {"Name": "HANARA", "Type": 70,
                                                "CallSign": "AB1"}}},
    )


def _market_rec():
    return Record(source="market", kind="overview", fetched_at=TS,
                  meta={"ttl_s": 600},
                  payload={"indices": [], "indicators": []})


def _count(sink, table):
    return sink.archive.query(f"SELECT COUNT(*) FROM {table}")[0][0]


def test_idempotent_writes_all_sources(tmp_path):
    sink = SqliteSink(tmp_path / "lake.db")
    records = [_quake_rec(), _news_rec(), _trend_rec(), _contrail_rec(),
               _wake_pos_rec(), _wake_static_rec(), _market_rec()]
    sink.write(records)
    sink.write(records)  # 재실행 — 전부 멱등이어야 함

    assert _count(sink, "quake_events") == 1
    assert _count(sink, "news_articles") == 1
    assert _count(sink, "trend_videos") == 2
    assert _count(sink, "trend_video_stats") == 2
    assert _count(sink, "contrail_aircraft") == 1
    assert _count(sink, "contrail_positions") == 1
    assert _count(sink, "wake_vessels") == 1
    assert _count(sink, "wake_positions") == 1
    assert _count(sink, "snapshots") == 1  # market — ts 동일 재기록은 스킵

    # trend rank = 배열 순서, ts = 주기 버킷 정렬값
    rows = sink.archive.query(
        "SELECT video_id, rank FROM trend_video_stats ORDER BY rank")
    assert rows == [("v1", 1), ("v2", 2)]

    # wake dim은 static 정보가 병합돼 있어야 함 (COALESCE 업서트)
    (vessel,) = sink.archive.query(
        "SELECT mmsi, name, ship_type, callsign FROM wake_vessels")
    assert vessel == ("440000001", "HANARA", "화물", "AB1")


def test_contrail_global_not_archived(tmp_path):
    sink = SqliteSink(tmp_path / "lake.db")
    sink.write([_contrail_rec(kind="global")])
    assert _count(sink, "contrail_aircraft") == 0  # 전세계 스냅샷은 홍수 방지로 제외
    assert _count(sink, "contrail_positions") == 0


def test_bad_record_is_isolated(tmp_path):
    sink = SqliteSink(tmp_path / "lake.db")
    bad = Record(source="news", kind="bbc", payload=12345, meta={}, fetched_at=TS)
    sink.write([bad, _quake_rec()])
    assert _count(sink, "quake_events") == 1  # 깨진 레코드가 배치를 못 죽임


def test_rebuild_from_raw_lake(tmp_path):
    from datalake.core.sqlite_sink import rebuild

    lake_root = tmp_path / "lake"
    FileSink(lake_root).write([_quake_rec(), _news_rec(), _market_rec()])

    db = tmp_path / "rebuilt.db"
    n = rebuild(lake_root, db)
    assert n == 3

    sink = SqliteSink(db)
    assert _count(sink, "quake_events") == 1
    assert _count(sink, "news_articles") == 1
    assert _count(sink, "snapshots") == 1

    # 재구축 재실행도 멱등
    assert rebuild(lake_root, db) == 3
    assert _count(sink, "quake_events") == 1
    assert _count(sink, "snapshots") == 1

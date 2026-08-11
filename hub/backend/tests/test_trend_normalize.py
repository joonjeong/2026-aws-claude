"""trend 정규화: 스냅샷 → dim(trend_videos)/fact(trend_video_stats) + 멱등 백필."""
from labkit import Archive

import app.archive as hub_archive
from app.modules.trend import config, schema
from app.modules.trend.collector.youtube import archive_trending
from app.modules.trend.migrate import migrate_snapshots

ITEM = {
    "video_id": "v1", "title": "First video", "channel": "ch-A",
    "category_id": "10", "thumbnail": "https://img/v1.jpg",
    "view_count": 1000, "like_count": 50,
    "published_at": "2026-08-10T00:00:00Z",
}
SNAPSHOT = {
    "captured_at": "2026-08-11T05:00:00Z",
    "items": [ITEM, {**ITEM, "video_id": "v2", "title": "Second video"}],
}


def make_archive(tmp_path, monkeypatch) -> Archive:
    a = Archive(tmp_path / "t.db")
    a.ensure_schema("trend", schema.DDL, schema.TABLES)
    monkeypatch.setattr(hub_archive, "archive", a)  # 헬퍼가 이 인스턴스를 쓰게
    return a


def test_archive_trending_writes_dim_and_fact_with_rank(tmp_path, monkeypatch):
    a = make_archive(tmp_path, monkeypatch)
    archive_trending(100, SNAPSHOT)
    ts = 100 * config.POLL_INTERVAL_S
    stats = a.query(
        "SELECT video_id, ts, rank, view_count, like_count"
        " FROM trend_video_stats ORDER BY rank"
    )
    assert stats == [("v1", ts, 1, 1000, 50), ("v2", ts, 2, 1000, 50)]
    dims = a.query(
        "SELECT video_id, title, channel, category_id, first_seen, last_seen"
        " FROM trend_videos ORDER BY video_id"
    )
    assert dims == [
        ("v1", "First video", "ch-A", "10", ts, ts),
        ("v2", "Second video", "ch-A", "10", ts, ts),
    ]


def test_archive_trending_rerun_idempotent_and_dim_tracks_latest(tmp_path, monkeypatch):
    a = make_archive(tmp_path, monkeypatch)
    archive_trending(100, SNAPSHOT)
    archive_trending(100, SNAPSHOT)  # 같은 버킷 재기록 → fact no-op
    assert a.query("SELECT COUNT(*) FROM trend_video_stats")[0][0] == 2
    # 다음 버킷: 제목 변경 + 조회수 증가 → dim은 최신 승리, first_seen은 유지
    later = {**SNAPSHOT, "items": [{**ITEM, "title": "Renamed", "view_count": 2000}]}
    archive_trending(101, later)
    ts0, ts1 = 100 * config.POLL_INTERVAL_S, 101 * config.POLL_INTERVAL_S
    row = a.query(
        "SELECT title, first_seen, last_seen FROM trend_videos WHERE video_id='v1'"
    )[0]
    assert row == ("Renamed", ts0, ts1)
    assert a.query("SELECT COUNT(*) FROM trend_video_stats")[0][0] == 3


def test_backfill_moves_snapshots_and_deletes_source(tmp_path, monkeypatch):
    a = make_archive(tmp_path, monkeypatch)
    a.put_snapshot("trend", "trending", {"bucket": 100, **SNAPSHOT})
    a.put_snapshot("trend", "trending", {"bucket": 101, **SNAPSHOT})
    assert migrate_snapshots() == 2
    assert a.query("SELECT COUNT(*) FROM trend_video_stats")[0][0] == 4
    assert a.query(
        "SELECT COUNT(*) FROM snapshots WHERE module='trend'"
    )[0][0] == 0
    assert migrate_snapshots() == 0  # 재실행 no-op


def test_backfill_malformed_snapshot_kept(tmp_path, monkeypatch):
    a = make_archive(tmp_path, monkeypatch)
    a.put_snapshot("trend", "trending", {"bucket": 100, **SNAPSHOT})
    a.put_snapshot("trend", "trending", {"items": []})  # bucket 누락 → 스킵
    a.put_snapshot("trend", "trending",
                   {"bucket": 102, "items": [{"video_id": "x"}]})  # 키 누락 → 스킵
    assert migrate_snapshots() == 1
    assert a.query("SELECT COUNT(*) FROM snapshots WHERE module='trend'")[0][0] == 2


def test_backfill_other_snapshots_untouched(tmp_path, monkeypatch):
    a = make_archive(tmp_path, monkeypatch)
    a.put_snapshot("market", "overview", {"indices": []})
    a.put_snapshot("trend", "trending", {"bucket": 100, **SNAPSHOT})
    migrate_snapshots()
    assert a.query("SELECT COUNT(*) FROM snapshots WHERE module='market'")[0][0] == 1

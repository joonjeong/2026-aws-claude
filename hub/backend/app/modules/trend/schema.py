"""Trend 정규화 스키마 — dim(trend_videos) 영구, fact(trend_video_stats) 보존기간.

fact의 rank는 스냅샷 items 배열 순서(=트렌딩 순위)를 명시화한 것.
ts는 bucket * POLL_INTERVAL_S (버킷 시작 유닉스초) — 버킷당 결정적이라
재기록·백필 어느 경로든 PK(video_id, ts)로 멱등.
"""

DDL = """
CREATE TABLE IF NOT EXISTS trend_videos (
  video_id     TEXT PRIMARY KEY,
  title        TEXT,
  channel      TEXT,
  category_id  TEXT,
  thumbnail    TEXT,
  published_at TEXT,
  first_seen   REAL NOT NULL,
  last_seen    REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS trend_video_stats (
  video_id   TEXT NOT NULL,
  ts         REAL NOT NULL,
  rank       INTEGER NOT NULL,
  view_count INTEGER,
  like_count INTEGER,
  PRIMARY KEY (video_id, ts)
);
CREATE INDEX IF NOT EXISTS idx_trend_video_stats_ts ON trend_video_stats (ts);
"""

TABLES = ["trend_videos", "trend_video_stats"]

# wake/contrail의 COALESCE와 달리 최신 승리: 제목·썸네일은 실제로 바뀌는 값이고
# _normalize_item이 항상 전 필드를 채워 보내므로 NULL 방어가 필요 없다.
UPSERT_VIDEO = """
INSERT INTO trend_videos
  (video_id, title, channel, category_id, thumbnail, published_at, first_seen, last_seen)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(video_id) DO UPDATE SET
  title        = excluded.title,
  channel      = excluded.channel,
  category_id  = excluded.category_id,
  thumbnail    = excluded.thumbnail,
  published_at = excluded.published_at,
  last_seen    = excluded.last_seen
"""

INSERT_STAT = """
INSERT OR IGNORE INTO trend_video_stats (video_id, ts, rank, view_count, like_count)
VALUES (?, ?, ?, ?, ?)
"""

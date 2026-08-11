"""SQLite 옵션 존 스키마 — hub 각 모듈 schema.py와 동형 (이식, import 금지).

hub DB(lab.db)와 조인·비교가 쉽도록 테이블명·컬럼을 그대로 유지한다.
market은 hub와 동일하게 snapshots(JSON) 사용 (DDL은 core/sqlite_sink.py).
"""

QUAKE_DDL = """
CREATE TABLE IF NOT EXISTS quake_events (
  id       TEXT PRIMARY KEY,
  mag      REAL,
  place    TEXT,
  time     INTEGER,
  lon      REAL,
  lat      REAL,
  depth_km REAL
);
CREATE INDEX IF NOT EXISTS idx_quake_events_time ON quake_events (time);
"""
QUAKE_TABLES = ["quake_events"]
QUAKE_INSERT = """
INSERT OR IGNORE INTO quake_events (id, mag, place, time, lon, lat, depth_km)
VALUES (?, ?, ?, ?, ?, ?, ?)
"""

NEWS_DDL = """
CREATE TABLE IF NOT EXISTS news_articles (
  link       TEXT PRIMARY KEY,
  source     TEXT NOT NULL,
  title      TEXT NOT NULL,
  published  TEXT,
  summary    TEXT,
  first_seen REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_news_articles_source_pub
  ON news_articles (source, published);
"""
NEWS_TABLES = ["news_articles"]
NEWS_INSERT = """
INSERT OR IGNORE INTO news_articles (link, source, title, published, summary, first_seen)
VALUES (?, ?, ?, ?, ?, ?)
"""

TREND_DDL = """
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
TREND_TABLES = ["trend_videos", "trend_video_stats"]
TREND_UPSERT_VIDEO = """
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
TREND_INSERT_STAT = """
INSERT OR IGNORE INTO trend_video_stats (video_id, ts, rank, view_count, like_count)
VALUES (?, ?, ?, ?, ?)
"""

CONTRAIL_DDL = """
CREATE TABLE IF NOT EXISTS contrail_aircraft (
  icao24 TEXT PRIMARY KEY,
  callsign TEXT,
  origin_country TEXT,
  first_seen REAL NOT NULL,
  last_seen REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS contrail_positions (
  icao24 TEXT NOT NULL,
  ts REAL NOT NULL,
  lon REAL NOT NULL,
  lat REAL NOT NULL,
  alt_m REAL,
  velocity_ms REAL,
  track_deg REAL,
  on_ground INTEGER,
  PRIMARY KEY (icao24, ts)
);
CREATE INDEX IF NOT EXISTS idx_contrail_positions_ts ON contrail_positions (ts);
"""
CONTRAIL_TABLES = ["contrail_aircraft", "contrail_positions"]
CONTRAIL_UPSERT_AIRCRAFT = """
INSERT INTO contrail_aircraft (icao24, callsign, origin_country, first_seen, last_seen)
VALUES (?, ?, ?, ?, ?)
ON CONFLICT(icao24) DO UPDATE SET
  last_seen      = excluded.last_seen,
  callsign       = COALESCE(excluded.callsign, contrail_aircraft.callsign),
  origin_country = COALESCE(excluded.origin_country, contrail_aircraft.origin_country)
"""
CONTRAIL_INSERT_POSITION = """
INSERT OR IGNORE INTO contrail_positions
  (icao24, ts, lon, lat, alt_m, velocity_ms, track_deg, on_ground)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""

WAKE_DDL = """
CREATE TABLE IF NOT EXISTS wake_vessels (
  mmsi TEXT PRIMARY KEY,
  name TEXT,
  ship_type TEXT,
  callsign TEXT,
  first_seen REAL NOT NULL,
  last_seen REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS wake_positions (
  mmsi TEXT NOT NULL,
  ts REAL NOT NULL,
  lon REAL NOT NULL,
  lat REAL NOT NULL,
  sog_kn REAL,
  cog_deg REAL,
  heading_deg REAL,
  PRIMARY KEY (mmsi, ts)
);
CREATE INDEX IF NOT EXISTS idx_wake_positions_ts ON wake_positions (ts);
"""
WAKE_TABLES = ["wake_vessels", "wake_positions"]
WAKE_UPSERT_VESSEL = """
INSERT INTO wake_vessels (mmsi, name, ship_type, callsign, first_seen, last_seen)
VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT(mmsi) DO UPDATE SET
  last_seen = excluded.last_seen,
  name      = COALESCE(excluded.name, wake_vessels.name),
  ship_type = COALESCE(excluded.ship_type, wake_vessels.ship_type),
  callsign  = COALESCE(excluded.callsign, wake_vessels.callsign)
"""
WAKE_INSERT_POSITION = """
INSERT OR IGNORE INTO wake_positions
  (mmsi, ts, lon, lat, sog_kn, cog_deg, heading_deg)
VALUES (?, ?, ?, ?, ?, ?, ?)
"""

FLASHPOINT_DDL = """
CREATE TABLE IF NOT EXISTS flashpoint_events (
  event_id  INTEGER PRIMARY KEY,
  ts        REAL NOT NULL,
  event_day TEXT,
  code      TEXT,
  root      TEXT,
  quad      INTEGER,
  goldstein REAL,
  mentions  INTEGER,
  articles  INTEGER,
  tone      REAL,
  actor1    TEXT,
  actor2    TEXT,
  lat       REAL NOT NULL,
  lon       REAL NOT NULL,
  country   TEXT,
  source_url TEXT
);
CREATE INDEX IF NOT EXISTS idx_flashpoint_events_ts ON flashpoint_events (ts);
"""
FLASHPOINT_TABLES = ["flashpoint_events"]
FLASHPOINT_INSERT = """
INSERT OR IGNORE INTO flashpoint_events
  (event_id, ts, event_day, code, root, quad, goldstein, mentions,
   articles, tone, actor1, actor2, lat, lon, country, source_url)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

# module → (ddl, tables) — SqliteSink가 ensure_schema에 사용
MODULES: dict[str, tuple[str, list[str]]] = {
    "quake": (QUAKE_DDL, QUAKE_TABLES),
    "news": (NEWS_DDL, NEWS_TABLES),
    "trend": (TREND_DDL, TREND_TABLES),
    "contrail": (CONTRAIL_DDL, CONTRAIL_TABLES),
    "wake": (WAKE_DDL, WAKE_TABLES),
    "flashpoint": (FLASHPOINT_DDL, FLASHPOINT_TABLES),
}

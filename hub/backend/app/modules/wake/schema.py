"""Wake 정규화 스키마 — dim(wake_vessels)은 영구, fact(wake_positions)는 보존기간."""

DDL = """
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

TABLES = ["wake_vessels", "wake_positions"]

UPSERT_VESSEL = """
INSERT INTO wake_vessels (mmsi, name, ship_type, callsign, first_seen, last_seen)
VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT(mmsi) DO UPDATE SET
  last_seen = excluded.last_seen,
  name      = COALESCE(excluded.name, wake_vessels.name),
  ship_type = COALESCE(excluded.ship_type, wake_vessels.ship_type),
  callsign  = COALESCE(excluded.callsign, wake_vessels.callsign)
"""

INSERT_POSITION = """
INSERT OR IGNORE INTO wake_positions
  (mmsi, ts, lon, lat, sog_kn, cog_deg, heading_deg)
VALUES (?, ?, ?, ?, ?, ?, ?)
"""

"""Contrail 정규화 스키마 — dim(contrail_aircraft) 영구, fact(contrail_positions) 보존기간."""

DDL = """
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

TABLES = ["contrail_aircraft", "contrail_positions"]

UPSERT_AIRCRAFT = """
INSERT INTO contrail_aircraft (icao24, callsign, origin_country, first_seen, last_seen)
VALUES (?, ?, ?, ?, ?)
ON CONFLICT(icao24) DO UPDATE SET
  last_seen      = excluded.last_seen,
  callsign       = COALESCE(excluded.callsign, contrail_aircraft.callsign),
  origin_country = COALESCE(excluded.origin_country, contrail_aircraft.origin_country)
"""

INSERT_POSITION = """
INSERT OR IGNORE INTO contrail_positions
  (icao24, ts, lon, lat, alt_m, velocity_ms, track_deg, on_ground)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""

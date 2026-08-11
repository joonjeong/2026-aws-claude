"""Flashpoint 스키마 — fact 단일 테이블 (이벤트는 일회성, quake_events 패턴)."""

DDL = """
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

TABLES = ["flashpoint_events"]

# 같은 15분 파일 재처리(재시작 등)는 PK 멱등으로 흡수
INSERT_EVENT = """
INSERT OR IGNORE INTO flashpoint_events
  (event_id, ts, event_day, code, root, quad, goldstein, mentions,
   articles, tone, actor1, actor2, lat, lon, country, source_url)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

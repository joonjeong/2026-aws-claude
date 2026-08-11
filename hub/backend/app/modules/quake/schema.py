"""Quake 정규화 스키마 — 점 이벤트 단일 테이블 (dim/fact 분리 없음, 스펙 §1)."""

DDL = """
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

TABLES = ["quake_events"]

INSERT_EVENT = """
INSERT OR IGNORE INTO quake_events (id, mag, place, time, lon, lat, depth_km)
VALUES (?, ?, ?, ?, ?, ?, ?)
"""

# quake_events에 실재하는 id만 삭제 — INSERT OR IGNORE rowcount는 중복 재실행 시
# 0이라 성공 판정에 쓸 수 없다 (스펙 §3). 이관 실패 행은 구조적으로 삭제 불가.
DELETE_MIGRATED = """
DELETE FROM entities
 WHERE module = 'quake' AND id IN (SELECT id FROM quake_events)
"""

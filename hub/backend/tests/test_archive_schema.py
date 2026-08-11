"""Archive 정규화 확장: 모듈 정의 테이블 등록·기록·조회·프루닝."""
import time

from labkit import Archive

DDL = """
CREATE TABLE IF NOT EXISTS t_vessels (
  mmsi TEXT PRIMARY KEY, name TEXT, first_seen REAL NOT NULL, last_seen REAL NOT NULL);
CREATE TABLE IF NOT EXISTS t_positions (
  mmsi TEXT NOT NULL, ts REAL NOT NULL, lon REAL NOT NULL, lat REAL NOT NULL,
  PRIMARY KEY (mmsi, ts));
"""

UPSERT = """
INSERT INTO t_vessels (mmsi, name, first_seen, last_seen) VALUES (?, ?, ?, ?)
ON CONFLICT(mmsi) DO UPDATE SET
  last_seen = excluded.last_seen,
  name = COALESCE(excluded.name, t_vessels.name)
"""


def make(tmp_path):
    a = Archive(tmp_path / "t.db")
    a.ensure_schema("testmod", DDL, ["t_vessels", "t_positions"])
    return a


def test_insert_query_and_counts(tmp_path):
    a = make(tmp_path)
    n = a.insert_rows(
        "INSERT OR IGNORE INTO t_positions (mmsi, ts, lon, lat) VALUES (?, ?, ?, ?)",
        [("1", 1.0, 127.0, 37.0), ("1", 2.0, 127.1, 37.0)],
    )
    assert n == 2
    assert a.insert_rows("INSERT OR IGNORE INTO t_positions VALUES (?, ?, ?, ?)", []) == 0
    rows = a.query("SELECT ts, lon FROM t_positions WHERE mmsi = ? ORDER BY ts", ("1",))
    assert [r[0] for r in rows] == [1.0, 2.0]
    assert a.counts().get("testmod") == 2


def test_dim_upsert_keeps_first_seen_and_fills_name(tmp_path):
    a = make(tmp_path)
    a.insert_rows(UPSERT, [("9", None, 100.0, 100.0)])
    a.insert_rows(UPSERT, [("9", "EVER GIVEN", 100.0, 200.0)])
    a.insert_rows(UPSERT, [("9", None, 100.0, 300.0)])  # None이 이름을 지우면 안 됨
    row = a.query("SELECT name, first_seen, last_seen FROM t_vessels WHERE mmsi='9'")[0]
    assert row == ("EVER GIVEN", 100.0, 300.0)


def test_prune_table_by_retention(tmp_path):
    a = make(tmp_path)
    old = time.time() - 10 * 86_400
    a.insert_rows(
        "INSERT OR IGNORE INTO t_positions (mmsi, ts, lon, lat) VALUES (?, ?, ?, ?)",
        [("1", old, 0, 0), ("1", time.time(), 0, 0)],
    )
    assert a.prune_table("t_positions", "ts", 7) == 1
    assert a.prune_table("t_positions", "ts", 0) == 0        # disabled
    assert a.prune_table("unregistered", "ts", 7) == 0       # 미등록 테이블 거부

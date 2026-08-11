"""quake entities JSON → quake_events 멱등 백필: 이관·삭제·격리·멱등성."""
from labkit import Archive

import app.archive as hub_archive
from app.modules.quake import schema
from app.modules.quake.migrate import migrate_entities

EVENT = {
    "id": "ev1", "mag": 4.5, "place": "somewhere, Alaska",
    "time": 1_786_300_000_000, "lon": -148.9, "lat": 62.2, "depth_km": 10.0,
}


def make_archive(tmp_path, monkeypatch) -> Archive:
    a = Archive(tmp_path / "t.db")
    a.ensure_schema("quake", schema.DDL, schema.TABLES)
    monkeypatch.setattr(hub_archive, "archive", a)  # 헬퍼가 이 인스턴스를 쓰게
    return a


def test_backfill_moves_rows_and_deletes_source(tmp_path, monkeypatch):
    a = make_archive(tmp_path, monkeypatch)
    a.put_entities("quake", [("ev1", EVENT), ("ev2", {**EVENT, "id": "ev2"})])
    assert migrate_entities() == 2
    assert a.query("SELECT COUNT(*) FROM quake_events")[0][0] == 2
    assert a.query("SELECT COUNT(*) FROM entities WHERE module='quake'")[0][0] == 0
    # 컬럼 매핑 검증 (id, mag, place, time, lon, lat, depth_km)
    row = a.query(
        "SELECT mag, place, time, lon, lat, depth_km FROM quake_events WHERE id='ev1'"
    )[0]
    assert row == (4.5, "somewhere, Alaska", 1_786_300_000_000, -148.9, 62.2, 10.0)


def test_idempotent_rerun_and_empty_noop(tmp_path, monkeypatch):
    a = make_archive(tmp_path, monkeypatch)
    a.put_entities("quake", [("ev1", EVENT)])
    migrate_entities()
    assert migrate_entities() == 0  # entities 비었으니 no-op
    assert a.query("SELECT COUNT(*) FROM quake_events")[0][0] == 1


def test_malformed_rows_skipped_and_kept(tmp_path, monkeypatch):
    a = make_archive(tmp_path, monkeypatch)
    a.put_entities("quake", [("good", EVENT)])
    # put_entities는 JSON을 강제하므로 비정상 payload는 직접 삽입
    a.insert_rows(
        "INSERT OR IGNORE INTO entities (module, id, first_seen, payload)"
        " VALUES (?, ?, ?, ?)",
        [("quake", "bad-json", 0.0, "not-json"),
         ("quake", "bad-keys", 0.0, '{"id":"bad-keys"}')],  # mag 등 누락 → KeyError
    )
    assert migrate_entities() == 1  # good만 파싱 성공
    ids = {r[0] for r in a.query("SELECT id FROM quake_events")}
    assert ids == {"good"}
    kept = {r[0] for r in a.query("SELECT id FROM entities WHERE module='quake'")}
    assert kept == {"bad-json", "bad-keys"}  # 비정상 행은 보존


def test_other_module_rows_untouched(tmp_path, monkeypatch):
    a = make_archive(tmp_path, monkeypatch)
    a.put_entities("news", [("article1", {"title": "x"})])
    a.put_entities("quake", [("ev1", EVENT)])
    migrate_entities()
    assert a.query("SELECT COUNT(*) FROM entities WHERE module='news'")[0][0] == 1

"""news 정규화: 수집 경로 기록 + entities JSON → news_articles 멱등 백필."""
from labkit import Archive

import app.archive as hub_archive
from app.modules.news import schema, service
from app.modules.news.migrate import migrate_entities

ARTICLE = {
    "source": "bbc", "title": "Sample headline",
    "link": "https://example.com/a1",
    "published": "2026-08-11T05:00:00Z", "summary": "Body snippet",
}


def make_archive(tmp_path, monkeypatch) -> Archive:
    a = Archive(tmp_path / "t.db")
    a.ensure_schema("news", schema.DDL, schema.TABLES)
    monkeypatch.setattr(hub_archive, "archive", a)  # 헬퍼가 이 인스턴스를 쓰게
    return a


def test_archive_articles_writes_normalized_rows(tmp_path, monkeypatch):
    a = make_archive(tmp_path, monkeypatch)
    service.archive_articles([ARTICLE, {**ARTICLE, "link": "https://example.com/a2"}])
    rows = a.query(
        "SELECT link, source, title, published, summary FROM news_articles ORDER BY link"
    )
    assert rows == [
        ("https://example.com/a1", "bbc", "Sample headline",
         "2026-08-11T05:00:00Z", "Body snippet"),
        ("https://example.com/a2", "bbc", "Sample headline",
         "2026-08-11T05:00:00Z", "Body snippet"),
    ]


def test_archive_articles_reobservation_keeps_first_seen(tmp_path, monkeypatch):
    a = make_archive(tmp_path, monkeypatch)
    service.archive_articles([ARTICLE])
    (first,) = a.query("SELECT first_seen FROM news_articles")[0]
    service.archive_articles([{**ARTICLE, "title": "Changed"}])  # 재관찰 no-op
    rows = a.query("SELECT title, first_seen FROM news_articles")
    assert rows == [("Sample headline", first)]


def test_backfill_moves_rows_and_deletes_source(tmp_path, monkeypatch):
    a = make_archive(tmp_path, monkeypatch)
    a.put_entities("news", [(ARTICLE["link"], ARTICLE)])
    assert migrate_entities() == 1
    assert a.query("SELECT COUNT(*) FROM news_articles")[0][0] == 1
    assert a.query("SELECT COUNT(*) FROM entities WHERE module='news'")[0][0] == 0
    row = a.query(
        "SELECT source, title, published, summary FROM news_articles WHERE link=?",
        (ARTICLE["link"],),
    )[0]
    assert row == ("bbc", "Sample headline", "2026-08-11T05:00:00Z", "Body snippet")


def test_backfill_uses_entities_first_seen(tmp_path, monkeypatch):
    a = make_archive(tmp_path, monkeypatch)
    a.insert_rows(
        "INSERT OR IGNORE INTO entities (module, id, first_seen, payload)"
        " VALUES (?, ?, ?, ?)",
        [("news", ARTICLE["link"], 123.0,
          '{"source":"bbc","title":"t","link":"https://example.com/a1"}')],
    )
    migrate_entities()
    assert a.query("SELECT first_seen FROM news_articles")[0][0] == 123.0


def test_backfill_malformed_rows_skipped_and_kept(tmp_path, monkeypatch):
    a = make_archive(tmp_path, monkeypatch)
    a.put_entities("news", [(ARTICLE["link"], ARTICLE)])
    a.insert_rows(
        "INSERT OR IGNORE INTO entities (module, id, first_seen, payload)"
        " VALUES (?, ?, ?, ?)",
        [("news", "bad-json", 0.0, "not-json"),
         ("news", "bad-keys", 0.0, '{"link":"bad-keys"}')],  # source/title 누락
    )
    assert migrate_entities() == 1
    kept = {r[0] for r in a.query("SELECT id FROM entities WHERE module='news'")}
    assert kept == {"bad-json", "bad-keys"}  # 비정상 행은 보존


def test_backfill_idempotent_and_other_modules_untouched(tmp_path, monkeypatch):
    a = make_archive(tmp_path, monkeypatch)
    a.put_entities("quake", [("ev1", {"id": "ev1"})])
    a.put_entities("news", [(ARTICLE["link"], ARTICLE)])
    migrate_entities()
    assert migrate_entities() == 0  # 재실행 no-op
    assert a.query("SELECT COUNT(*) FROM news_articles")[0][0] == 1
    assert a.query("SELECT COUNT(*) FROM entities WHERE module='quake'")[0][0] == 1

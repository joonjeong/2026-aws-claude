"""News 정규화 스키마 — 불변 점 레코드 단일 테이블 (quake_events와 동형, dim/fact 없음)."""

DDL = """
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

TABLES = ["news_articles"]

INSERT_ARTICLE = """
INSERT OR IGNORE INTO news_articles (link, source, title, published, summary, first_seen)
VALUES (?, ?, ?, ?, ?, ?)
"""

# news_articles에 실재하는 link만 삭제 — INSERT OR IGNORE rowcount는 재실행 시
# 0이라 성공 판정에 쓸 수 없다 (quake 백필과 동일한 존재검증 패턴).
DELETE_MIGRATED = """
DELETE FROM entities
 WHERE module = 'news' AND id IN (SELECT link FROM news_articles)
"""

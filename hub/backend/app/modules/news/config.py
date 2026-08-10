"""Newsroom Lens configuration.

Feed URLs were confirmed against each outlet's official RSS hub on
2026-08-10 (curl → HTTP 200, parseable RSS 2.0), per docs/newsroom.md #2.
"""
from labkit.config import env_int, env_str

# Each source: {id, name, lang, rss_url}
SOURCES: list[dict] = [
    {
        "id": "bbc",
        "name": "BBC World",
        "lang": "en",
        # Confirmed 2026-08-10 via BBC's official feed host feeds.bbci.co.uk
        # (linked from bbc.co.uk/news RSS hub). HTTP 200, RSS 2.0.
        "rss_url": "http://feeds.bbci.co.uk/news/world/rss.xml",
    },
    {
        "id": "guardian",
        "name": "The Guardian World",
        "lang": "en",
        # Confirmed 2026-08-10 — the Guardian exposes RSS by appending /rss
        # to any section URL (official Guardian RSS mechanism). HTTP 200, RSS 2.0.
        "rss_url": "https://www.theguardian.com/world/rss",
    },
    {
        "id": "nhk",
        "name": "NHK 국제 (NHK World 대체)",
        "lang": "ja",
        # SUBSTITUTION, confirmed 2026-08-10: NHK World's English news service
        # publishes NO official RSS/Atom feed (https://www3.nhk.or.jp/nhkworld/
        # en/news/feeds/ → 404; the news page links no feed; only a 1-item
        # audio podcast exists, unusable for headlines). The closest official
        # alternative is NHK's own RSS hub (https://www.nhk.or.jp/toppage/rss/
        # index.html), whose 国際/International feed is below. Japanese-language;
        # the lens output is Korean regardless. HTTP 200, RSS 2.0.
        "rss_url": "https://news.web.nhk/n-data/conf/na/rss/cat6.xml",
    },
    {
        "id": "yna",
        "name": "연합뉴스 국제",
        "lang": "ko",
        # Confirmed 2026-08-10 via Yonhap's official RSS hub
        # (https://www.yna.co.kr/rss/index — 국제 feed). HTTP 200, RSS 2.0.
        "rss_url": "https://www.yna.co.kr/rss/international.xml",
    },
]

# Collection
POLL_INTERVAL_S: int = env_int("NEWSROOM_POLL_INTERVAL_S", 120)  # per spec: 120s
FETCH_LATEST_N: int = 15          # newest N normalized per source per cycle
STORE_MAX_PER_SOURCE: int = 50    # IdempotentStore cap per source
SUMMARY_MAX_CHARS: int = 300      # HTML-stripped summary truncation

# Lens (Bedrock Converse via labkit)
LENS_MAX_TOKENS: int = 1500
LENS_BUCKET_S: int = 600          # same 10-minute bucket → cached answer
LENS_MODEL: str = env_str("NEWSROOM_LENS_MODEL", "global.anthropic.claude-sonnet-4-6")
LENS_REGION: str = env_str("NEWSROOM_LENS_REGION", "ap-northeast-2")

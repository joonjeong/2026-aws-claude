"""Trend Radar configuration — env-overridable via labkit.config helpers.

Keys (YT_API_KEY, AWS_BEARER_TOKEN_BEDROCK) live in environment variables
only and are read where they are used; they are never stored or logged here.
"""
from __future__ import annotations

from labkit.config import env_int, env_str

# Polling: workshop mode 60s (the original service uses 3600s).
POLL_INTERVAL_S = env_int("POLL_INTERVAL_S", 60)

# Snapshot ring buffer keeps the most recent 48 buckets.
SNAPSHOT_CAPACITY = 48

# 정규화 fact(trend_video_stats) 보존일 — dim(trend_videos)은 영구.
STATS_RETENTION_DAYS = env_int("TREND_STATS_RETENTION_DAYS", 30)

REGION_CODE = env_str("REGION_CODE", "KR")
MAX_RESULTS = 30

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
YT_API_KEY_ENV = "YT_API_KEY"
YT_FIXTURE_ENV = "YT_FIXTURE"

# LLM briefing
BRIEF_MAX_TOKENS = 800

# The 8 fixed filter categories (YouTube category id -> chip label).
FILTER_CATEGORIES: dict[str, str] = {
    "10": "Music",
    "20": "Gaming",
    "24": "Entertainment",
    "25": "News & Politics",
    "17": "Sports",
    "1": "Film & Animation",
    "28": "Science & Tech",
    "23": "Comedy",
}

# Default Korean category names, used when videoCategories(hl=ko) is
# unavailable at startup (no key / upstream failure).
DEFAULT_CATEGORY_NAMES: dict[str, str] = {
    "1": "영화/애니메이션",
    "2": "자동차",
    "10": "음악",
    "15": "반려동물/동물",
    "17": "스포츠",
    "19": "여행/이벤트",
    "20": "게임",
    "22": "인물/블로그",
    "23": "코미디",
    "24": "엔터테인먼트",
    "25": "뉴스/정치",
    "26": "노하우/스타일",
    "27": "교육",
    "28": "과학기술",
    "29": "비영리/사회운동",
}

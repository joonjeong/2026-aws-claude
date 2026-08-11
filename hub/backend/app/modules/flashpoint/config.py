"""Flashpoint module constants (env-overridable via labkit.config helpers).

GDELT v2 15분 export CSV — 무료·무키. 수시 조회 API가 아닌 파일 다운로드
경로라 폴링 주기(기본 900s)와 소스 갱신 주기가 자연스럽게 일치한다.
"""
from labkit.config import env_float, env_int, env_str

LASTUPDATE_URL = env_str(
    "FLASHPOINT_LASTUPDATE_URL",
    "http://data.gdeltproject.org/gdeltv2/lastupdate.txt",
)
POLL_S = env_float("FLASHPOINT_POLL_S", 900.0)
FETCH_TIMEOUT_S = env_float("FLASHPOINT_FETCH_TIMEOUT_S", 30.0)

# CAMEO 루트코드 필터 — 14 시위 ~ 20 대량폭력 (설계 §7)
ROOTS = {
    r.strip()
    for r in env_str("FLASHPOINT_ROOTS", "14,15,16,17,18,19,20").split(",")
    if r.strip()
}
ROOT_LABELS = {
    "14": "시위", "15": "무력과시", "16": "관계축소",
    "17": "강압", "18": "폭행", "19": "교전", "20": "대량폭력",
}

RETENTION_DAYS = env_int("FLASHPOINT_RETENTION_DAYS", 14)
EVENTS_LIMIT = env_int("FLASHPOINT_EVENTS_LIMIT", 2000)

BRIEF_MAX_TOKENS = env_int("FLASHPOINT_BRIEF_MAX_TOKENS", 700)
BRIEF_BUCKET_S = env_int("FLASHPOINT_BRIEF_BUCKET_S", 600)

# 관심 지역 프리셋 — bbox = (lat_min, lon_min, lat_max, lon_max)
PRESETS: list[dict] = [
    {"id": "hormuz", "label": "호르무즈·걸프", "bbox": (23.0, 47.0, 31.0, 60.0)},
    {"id": "mideast", "label": "중동", "bbox": (12.0, 32.0, 40.0, 64.0)},
    {"id": "ukraine", "label": "우크라이나", "bbox": (44.0, 22.0, 53.0, 41.0)},
    {"id": "taiwan", "label": "대만해협", "bbox": (20.0, 115.0, 28.0, 125.0)},
]
DEFAULT_PRESET = env_str("FLASHPOINT_DEFAULT_PRESET", "hormuz")

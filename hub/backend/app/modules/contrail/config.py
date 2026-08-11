"""Contrail module constants (env-overridable via labkit.config helpers).

무료 한도 예산 (스펙 §2): OAuth 시 전 세계 300s + 지역 60s = 일 ~2,592크레딧
(한도 4,000). 익명 시 900s/300s = 일 ~400크레딧 한도 내.
"""
from labkit.config import env_float, env_int, env_str

OPENSKY_URL = env_str(
    "CONTRAIL_OPENSKY_URL", "https://opensky-network.org/api/states/all"
)
TOKEN_URL = env_str(
    "CONTRAIL_OPENSKY_TOKEN_URL",
    "https://auth.opensky-network.org/auth/realms/opensky-network"
    "/protocol/openid-connect/token",
)
CLIENT_ID = env_str("CONTRAIL_OPENSKY_CLIENT_ID", "")
CLIENT_SECRET = env_str("CONTRAIL_OPENSKY_CLIENT_SECRET", "")
HAS_AUTH = bool(CLIENT_ID and CLIENT_SECRET)

GLOBAL_INTERVAL_S = env_float(
    "CONTRAIL_GLOBAL_INTERVAL_S", 300.0 if HAS_AUTH else 900.0
)
REGION_INTERVAL_S = env_float(
    "CONTRAIL_REGION_INTERVAL_S", 60.0 if HAS_AUTH else 300.0
)
FETCH_TIMEOUT_S = env_float("CONTRAIL_FETCH_TIMEOUT_S", 15.0)

TRAIL_WINDOW_S = env_float("CONTRAIL_TRAIL_WINDOW_S", 21_600.0)  # 6시간
TRAIL_GAP_S = env_float("CONTRAIL_TRAIL_GAP_S", 60.0)
TRAIL_MIN_MOVE_KM = env_float("CONTRAIL_TRAIL_MIN_MOVE_KM", 1.0)  # 항공기는 빠름
STALE_S = env_float("CONTRAIL_STALE_S", 900.0)                    # 15분 미관측 퇴출
MAX_ENTITIES = env_int("CONTRAIL_MAX_ENTITIES", 5_000)

ARCHIVE_GAP_S = env_float("CONTRAIL_ARCHIVE_GAP_S", 300.0)
POSITIONS_RETENTION_DAYS = env_int("CONTRAIL_POSITIONS_RETENTION_DAYS", 7)

BRIEF_MAX_TOKENS = env_int("CONTRAIL_BRIEF_MAX_TOKENS", 700)
BRIEF_BUCKET_S = env_int("CONTRAIL_BRIEF_BUCKET_S", 600)

# 관심 지역 프리셋 — wake와 동일 기본 목록 (bbox = lat_min, lon_min, lat_max, lon_max)
PRESETS: list[dict] = [
    {"id": "kr", "label": "한반도 주변", "bbox": (30.0, 120.0, 45.0, 135.0)},
    {"id": "taiwan", "label": "대만해협", "bbox": (20.0, 115.0, 28.0, 125.0)},
    {"id": "sea", "label": "동남아", "bbox": (-10.0, 95.0, 15.0, 120.0)},
]
DEFAULT_PRESET = env_str("CONTRAIL_DEFAULT_PRESET", "kr")

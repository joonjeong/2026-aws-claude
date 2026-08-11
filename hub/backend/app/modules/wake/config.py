"""Wake module constants (env-overridable via labkit.config helpers)."""
from labkit.config import env_float, env_int, env_str

AIS_URL = env_str("WAKE_AIS_URL", "wss://stream.aisstream.io/v0/stream")
AIS_KEY = env_str("WAKE_AIS_KEY", "")

TRAIL_WINDOW_S = env_float("WAKE_TRAIL_WINDOW_S", 21_600.0)   # 6시간
TRAIL_GAP_S = env_float("WAKE_TRAIL_GAP_S", 60.0)
TRAIL_MIN_MOVE_KM = env_float("WAKE_TRAIL_MIN_MOVE_KM", 0.5)
STALE_S = env_float("WAKE_STALE_S", 3_600.0)                  # 60분 미관측 퇴출
MAX_ENTITIES = env_int("WAKE_MAX_ENTITIES", 5_000)

ARCHIVE_GAP_S = env_float("WAKE_ARCHIVE_GAP_S", 300.0)        # fact 기록 개체당 간격
POSITIONS_RETENTION_DAYS = env_int("WAKE_POSITIONS_RETENTION_DAYS", 7)

BRIEF_MAX_TOKENS = env_int("WAKE_BRIEF_MAX_TOKENS", 700)
BRIEF_BUCKET_S = env_int("WAKE_BRIEF_BUCKET_S", 600)

PRESET_COOLDOWN_S = env_float("WAKE_PRESET_COOLDOWN_S", 10.0)  # 프리셋 전환 최소 간격

# 관심 지역 프리셋 — bbox는 (lat_min, lon_min, lat_max, lon_max).
# contrail과 동일 기본 목록 (스펙 §2), 선택 상태는 모듈별 독립.
PRESETS: list[dict] = [
    {"id": "kr", "label": "한반도 주변", "bbox": (30.0, 120.0, 45.0, 135.0)},
    {"id": "taiwan", "label": "대만해협", "bbox": (20.0, 115.0, 28.0, 125.0)},
    {"id": "sea", "label": "동남아", "bbox": (-10.0, 95.0, 15.0, 120.0)},
]
DEFAULT_PRESET = env_str("WAKE_DEFAULT_PRESET", "kr")

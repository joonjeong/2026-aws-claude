"""Contrail module constants (env-overridable via labkit.config helpers).

데이터 소스 (CONTRAIL_SOURCE):
  adsblol(기본) — adsb.lol re-api. bbox 직접 조회, 키·인증 불요.
    OpenSky가 AWS 등 데이터센터 IP의 TCP 연결을 드롭해 Fargate에서
    ConnectTimeout으로 전량 실패했던 것의 대체 (2026-08-11).
    국가 정보(origin_country)는 이 소스에 없어 null로 퇴화.
  opensky — 레거시 경로(로컬/개발용 롤백). 무료 한도 예산:
    지역 폴러가 사이클마다 프리셋 4개 bbox를 각각 조회하므로(상시 수집 구조)
    지역 크레딧이 프리셋 수에 비례한다. OAuth 기본값 기준
    전 세계 300s(288×4) + 지역 180s(480×4×1) = 일 ~3,072크레딧(한도 4,000).
    익명(한도 400)은 4프리셋 상시 수집을 감당 못 함 — 429는 폴러 실패 로그로
    드러나며, 필요하면 CONTRAIL_REGION_INTERVAL_S를 크게 잡아 완화.
"""
from labkit.config import env_float, env_int, env_str

SOURCE = env_str("CONTRAIL_SOURCE", "adsblol")  # adsblol | opensky

ADSBLOL_URL = env_str("CONTRAIL_ADSBLOL_URL", "https://re-api.adsb.lol/")

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

# 기본 주기 — opensky는 크레딧 예산에 맞춤, adsblol은 무료·무인증이지만
# 전 세계 스냅샷이 ~4MB라 커뮤니티 서비스에 부담 없게 600s로 보수적으로.
# 지역은 사이클마다 프리셋 bbox 4개 병렬 조회(요청당 수십 KB).
if SOURCE == "opensky":
    _GLOBAL_DEFAULT = 300.0 if HAS_AUTH else 900.0
    _REGION_DEFAULT = 180.0 if HAS_AUTH else 900.0
else:
    _GLOBAL_DEFAULT, _REGION_DEFAULT = 600.0, 60.0

GLOBAL_INTERVAL_S = env_float("CONTRAIL_GLOBAL_INTERVAL_S", _GLOBAL_DEFAULT)
REGION_INTERVAL_S = env_float("CONTRAIL_REGION_INTERVAL_S", _REGION_DEFAULT)
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

# 관심 지역 프리셋 — 항공 트래픽 밀집 지역 위주 (bbox = lat_min, lon_min, lat_max, lon_max).
# 2026-08-11 adsb.lol 실측(15:08 KST, 전지구 6,394대): 유럽 중부 1,735 · 일본 308 ·
# 미국 동부 348(현지 심야 최저점, 낮에는 세계 최다) · 한반도 172. wake(해역)와는 별도 목록.
PRESETS: list[dict] = [
    {"id": "kr", "label": "한반도 주변", "bbox": (30.0, 120.0, 45.0, 135.0)},
    {"id": "japan", "label": "일본", "bbox": (30.0, 128.0, 43.0, 146.0)},
    {"id": "europe", "label": "유럽 중부", "bbox": (43.0, -5.0, 55.0, 20.0)},
    {"id": "us-east", "label": "미국 동부", "bbox": (25.0, -90.0, 45.0, -70.0)},
]
DEFAULT_PRESET = env_str("CONTRAIL_DEFAULT_PRESET", "kr")

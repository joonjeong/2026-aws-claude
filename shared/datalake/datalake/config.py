"""datalake 전역 설정 — hub와 분리된 자체 env 네임스페이스(DATALAKE_*).

소스별 주기 env는 각 소스 모듈이 소유한다 (기본값 = hub와 동일).
"""

from __future__ import annotations

import os
from pathlib import Path

from .core.env import env_float, env_int

# 데이터 루트: shared/datalake/data (gitignore 대상)
_DEFAULT_ROOT = Path(__file__).resolve().parent.parent / "data"
ROOT = Path(os.environ.get("DATALAKE_ROOT", str(_DEFAULT_ROOT)))

# 스트림 소스 버퍼 플러시 주기
FLUSH_S = env_float("DATALAKE_FLUSH_S", 10.0)

# SQLite 옵션 존 (설계 §5.2) — raw가 진실의 원천, DB는 파생
SQLITE_ENABLED = os.environ.get("DATALAKE_SQLITE", "0") == "1"
DB_PATH = Path(os.environ.get("DATALAKE_DB_PATH", str(ROOT / "datalake.db")))

# 유지보수 (설계 §5.1): 전일 파티션 gzip(기본 켜짐) + 보존기간(0 = 무제한)
COMPRESS_ENABLED = os.environ.get("DATALAKE_COMPRESS", "1") == "1"
RAW_RETENTION_DAYS = env_int("DATALAKE_RAW_RETENTION_DAYS", 0)

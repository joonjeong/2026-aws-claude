"""장시간 판정 — hub market core/hours.py 이식 (주중 + 로컬 시간창, 휴장일 없음).

datalake의 market 폴은 30s 틱이지만 kind별 TTL 게이트(장중 45s/장외 600s)를
통과할 때만 상류를 호출한다 — 실효 호출 빈도가 hub와 동일해지는 지점.
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from labkit.config import env_int

_ET = ZoneInfo("America/New_York")
_KST = ZoneInfo("Asia/Seoul")

TTL_OPEN = env_int("DATALAKE_MARKET_TTL_OPEN", 45)      # hub MARKET_TTL_OPEN
TTL_CLOSED = env_int("DATALAKE_MARKET_TTL_CLOSED", 600)  # hub MARKET_TTL_CLOSED


def _in_window(tz: ZoneInfo, start: time, end: time,
               now: datetime | None = None) -> bool:
    local = (now.astimezone(tz) if now is not None else datetime.now(tz))
    return local.weekday() < 5 and start <= local.time() < end


def us_market_open(now: datetime | None = None) -> bool:
    return _in_window(_ET, time(9, 30), time(16, 0), now)


def kr_market_open(now: datetime | None = None) -> bool:
    return _in_window(_KST, time(9, 0), time(15, 30), now)


def ttl_for(kind: str, now: datetime | None = None) -> int:
    """kind별 실효 TTL — overview는 두 시장 중 하나라도 열려 있으면 빠르게."""
    if kind == "quotes_us":
        is_open = us_market_open(now)
    elif kind == "quotes_kr":
        is_open = kr_market_open(now)
    else:  # overview
        is_open = us_market_open(now) or kr_market_open(now)
    return TTL_OPEN if is_open else TTL_CLOSED

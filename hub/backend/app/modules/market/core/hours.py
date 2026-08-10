"""Market-hours-aware TTL: open 45s / closed 600s.

Simple weekday + local-time windows (US 09:30-16:00 ET, KR 09:00-15:30 KST).
No holiday calendar (YAGNI per design doc).
"""
from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from . import config

_ET = ZoneInfo("America/New_York")
_KST = ZoneInfo("Asia/Seoul")


def _in_window(tz: ZoneInfo, start: time, end: time) -> bool:
    now = datetime.now(tz)
    return now.weekday() < 5 and start <= now.time() < end


def us_market_open() -> bool:
    return _in_window(_ET, time(9, 30), time(16, 0))


def kr_market_open() -> bool:
    return _in_window(_KST, time(9, 0), time(15, 30))


def quote_ttl(market: str) -> int:
    """TTL for quote-like data of one market ('US' | 'KR')."""
    is_open = us_market_open() if market == "US" else kr_market_open()
    return config.TTL_OPEN if is_open else config.TTL_CLOSED


def overview_ttl() -> int:
    """Overview mixes both markets — refresh fast if either is open."""
    return config.TTL_OPEN if (us_market_open() or kr_market_open()) else config.TTL_CLOSED

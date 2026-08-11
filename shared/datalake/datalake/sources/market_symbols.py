"""market 수집 대상 목록 로더 — yfinance·pykrx 상류가 공유.

목록은 market_symbols.toml이 관리 (env DATALAKE_MARKET_SYMBOLS로 교체).
활성 수는 env DATALAKE_MARKET_ACTIVE_US/KR(기본 20) — 목록 앞에서 슬라이스.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from ..core.env import env_int


def _load() -> dict:
    override = os.environ.get("DATALAKE_MARKET_SYMBOLS")
    path = (Path(override) if override
            else Path(__file__).with_name("market_symbols.toml"))
    return tomllib.loads(path.read_text(encoding="utf-8"))


_DATA = _load()

US_SYMBOLS: list[tuple[str, str]] = [tuple(x) for x in _DATA["us"]["symbols"]]
KR_SYMBOLS: list[tuple[str, str]] = [tuple(x) for x in _DATA["kr"]["symbols"]]
INDICES: list[tuple[str, str, str]] = [tuple(x) for x in _DATA["indices"]["items"]]
INDICATORS: list[tuple[str, str]] = [tuple(x) for x in _DATA["indicators"]["items"]]

ACTIVE_US = US_SYMBOLS[:env_int("DATALAKE_MARKET_ACTIVE_US", 20)]
ACTIVE_KR = KR_SYMBOLS[:env_int("DATALAKE_MARKET_ACTIVE_KR", 20)]

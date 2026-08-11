"""env 헬퍼 — 비정상 값은 조용히 기본값으로 (수집기는 기동이 우선)."""

from __future__ import annotations

import os


def env_str(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value else default


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


def env_float(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default

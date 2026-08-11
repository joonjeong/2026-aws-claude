"""GDELT v2 export 정규화 — 헤더 없는 탭 구분 61컬럼 (인덱스 계약은 스펙 §2).

좌표 없는 행(~9%)과 루트코드 필터 밖은 스킵, 기형 행은 건별 격리.
"""
from __future__ import annotations

import calendar
import logging
import time
from typing import Iterable

logger = logging.getLogger(__name__)

# 사용 컬럼 인덱스 (GDELT 2.0 event table, 실측 검증 2026-08-11)
_ID, _SQLDATE, _ACTOR1, _ACTOR2 = 0, 1, 6, 16
_CODE, _ROOT, _QUAD, _GOLDSTEIN = 26, 28, 29, 30
_MENTIONS, _ARTICLES, _TONE = 31, 33, 34
_COUNTRY, _LAT, _LON, _DATEADDED, _URL = 53, 56, 57, 59, 60


def _clean(raw: str) -> str | None:
    s = raw.strip()
    return s or None


def _clean_url(raw: str) -> str | None:
    """href로 렌더링되는 값 — http(s) 외 스킴(javascript: 등)은 저장 전 차단."""
    s = raw.strip()
    return s if s.startswith(("http://", "https://")) else None


def _num(raw: str, cast) -> float | int | None:
    try:
        return cast(raw)
    except (TypeError, ValueError):
        return None


def _ts(dateadded: str) -> float:
    """DATEADDED(YYYYMMDDHHMMSS, UTC) → epoch. 실패 시 현재 시각."""
    try:
        st = time.strptime(dateadded, "%Y%m%d%H%M%S")
        return float(calendar.timegm(st))
    except ValueError:
        return time.time()


def normalize_export(lines: Iterable[str], roots: set[str]) -> list[dict]:
    out: list[dict] = []
    for line in lines:
        try:
            c = line.split("\t")
            if len(c) < 61 or c[_ROOT] not in roots:
                continue
            if not c[_LAT] or not c[_LON]:
                continue
            event_id = _num(c[_ID], int)
            if event_id is None:
                continue
            out.append({
                "event_id": event_id,
                "ts": _ts(c[_DATEADDED]),
                "event_day": c[_SQLDATE] or None,
                "code": c[_CODE] or None,
                "root": c[_ROOT],
                "quad": _num(c[_QUAD], int),
                "goldstein": _num(c[_GOLDSTEIN], float),
                "mentions": _num(c[_MENTIONS], int),
                "articles": _num(c[_ARTICLES], int),
                "tone": _num(c[_TONE], float),
                "actor1": _clean(c[_ACTOR1]),
                "actor2": _clean(c[_ACTOR2]),
                "lat": float(c[_LAT]),
                "lon": float(c[_LON]),
                "country": _clean(c[_COUNTRY]),
                "source_url": _clean_url(c[_URL]),
            })
        except Exception:  # 한 행의 비정상이 배치를 죽이지 않음
            logger.warning("skipping malformed gdelt row", exc_info=True)
    return out

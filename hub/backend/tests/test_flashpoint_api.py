"""이벤트 조회 쿼리 조립·통계 집계·브리핑 텍스트."""
import pytest
from fastapi import HTTPException

from app.modules.flashpoint.api import _resolve_preset, _stats, events_query
from app.modules.flashpoint.llm import build_user_text


def ev(root="19", country="IR", mentions=5, **kw):
    base = {
        "event_id": 1, "ts": 1000.0, "root": root, "code": "190",
        "country": country, "mentions": mentions, "actor1": "A", "actor2": "B",
        "lat": 26.0, "lon": 56.0, "goldstein": -10.0, "tone": -5.0,
        "articles": 3, "event_day": "20260811", "source_url": "https://x",
    }
    return {**base, **kw}


def test_health_exposes_ingest_counters():
    import app.modules.flashpoint as fp  # __init__의 재바인딩 이후 경로로 검증

    h = fp.health()
    assert h["last_batch"] == 0 and h["total_rows"] == 0
    assert h["collector"]["name"] == "flashpoint-gdelt"


def test_events_query_global_has_no_bbox_clause():
    sql, params = events_query(cutoff=123.0, bbox=None)
    assert "lat BETWEEN" not in sql
    assert params[0] == 123.0


def test_events_query_bbox_filters_lat_lon():
    sql, params = events_query(cutoff=0.0, bbox=(23.0, 47.0, 31.0, 60.0))
    assert "lat BETWEEN ? AND ?" in sql and "lon BETWEEN ? AND ?" in sql
    assert params == (0.0, 23.0, 31.0, 47.0, 60.0)


def test_resolve_preset_default_and_unknown():
    assert _resolve_preset(None) is None                # 전 세계 (bbox 없음)
    assert _resolve_preset("hormuz")["id"] == "hormuz"
    with pytest.raises(HTTPException):
        _resolve_preset("nope")


def test_stats_aggregates_by_root_and_country():
    events = [ev(), ev(root="14", country="KR"), ev(root="19", country="IR")]
    s = _stats(events)
    assert s["count"] == 3
    assert s["by_root"]["19"] == 2 and s["by_root"]["14"] == 1
    assert s["top_country"] == "IR"


def test_brief_text_uses_korean_root_labels():
    txt = build_user_text(
        {"count": 2, "by_root": {"19": 2}, "top_country": "IR", "last_fetch": None},
        "호르무즈·걸프",
        [ev(mentions=42)],
    )
    assert "교전" in txt            # root 19 한국어 라벨
    assert "호르무즈·걸프" in txt
    assert "42" in txt              # 언급 수

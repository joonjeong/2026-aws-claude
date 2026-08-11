"""전역 통계·브리핑 텍스트가 adsblol 기준(기종)으로 집계되는지."""
from app.modules.contrail.api import _global_stats
from app.modules.contrail.llm import build_user_text


def test_global_stats_top_type_counts_only_known_types():
    flights = [
        {"type": "A359", "on_ground": False},
        {"type": "A359", "on_ground": False},
        {"type": "B738", "on_ground": True},
        {"type": None, "on_ground": False},  # 기종 미상은 집계 제외
    ]
    s = _global_stats(flights)
    assert s["top_type"] == "A359"
    assert "top_country" not in s


def test_global_stats_top_type_none_when_source_has_no_types():
    # opensky 롤백 경로: 기종 정보가 전혀 없으면 None (프론트는 "-" 표시)
    s = _global_stats([{"type": None, "on_ground": False}])
    assert s["top_type"] is None


def test_brief_text_uses_aircraft_type():
    txt = build_user_text(
        {"count": 3, "airborne": 2, "top_type": "A359"},
        {"count": 1},
        "한반도 주변",
        [{"id": "71bf71", "callsign": "KAL123", "type": "A359",
          "alt_m": 9144.0, "velocity_ms": 230.0}],
    )
    assert "최다 기종: A359" in txt
    assert "KAL123 | A359" in txt

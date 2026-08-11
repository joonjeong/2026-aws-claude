"""GDELT v2 export 행 정규화 — 61컬럼 인덱스 계약, 필터, 건별 격리."""
import calendar

from app.modules.flashpoint.normalize import normalize_export

ROOTS = {"14", "15", "16", "17", "18", "19", "20"}


def row(overrides: dict | None = None) -> str:
    """61컬럼 GDELT export 행 — 스펙 §2의 사용 인덱스만 채우고 나머지 공백."""
    cols = [""] * 61
    cols[0] = "1234567890"          # GlobalEventID
    cols[1] = "20260810"            # SQLDATE (이벤트 발생일)
    cols[6] = "IRAN  "              # Actor1Name (후행 공백)
    cols[16] = "UNITED STATES"      # Actor2Name
    cols[26] = "190"                # EventCode
    cols[28] = "19"                 # EventRootCode
    cols[29] = "4"                  # QuadClass
    cols[30] = "-10.0"              # GoldsteinScale
    cols[31] = "24"                 # NumMentions
    cols[33] = "12"                 # NumArticles
    cols[34] = "-7.5"               # AvgTone
    cols[53] = "IR"                 # ActionGeo_CountryCode
    cols[56] = "26.5667"            # ActionGeo_Lat
    cols[57] = "56.25"              # ActionGeo_Long
    cols[59] = "20260811064500"     # DATEADDED (UTC)
    cols[60] = "https://example.com/article"
    for i, v in (overrides or {}).items():
        cols[i] = v
    return "\t".join(cols)


def test_normalize_good_row_maps_all_fields():
    out = normalize_export([row()], roots=ROOTS)
    assert len(out) == 1
    e = out[0]
    assert e["event_id"] == 1234567890
    assert e["ts"] == calendar.timegm((2026, 8, 11, 6, 45, 0, 0, 0, 0))
    assert e["event_day"] == "20260810"
    assert e["code"] == "190" and e["root"] == "19" and e["quad"] == 4
    assert e["goldstein"] == -10.0 and e["mentions"] == 24
    assert e["articles"] == 12 and e["tone"] == -7.5
    assert e["actor1"] == "IRAN" and e["actor2"] == "UNITED STATES"
    assert e["lat"] == 26.5667 and e["lon"] == 56.25
    assert e["country"] == "IR"
    assert e["source_url"] == "https://example.com/article"


def test_skips_rows_without_coordinates():
    assert normalize_export([row({56: "", 57: ""})], roots=ROOTS) == []


def test_skips_roots_outside_filter():
    assert normalize_export([row({28: "04"})], roots=ROOTS) == []  # 04 = 협의


def test_malformed_rows_isolated():
    out = normalize_export(["short\trow", row(), ""], roots=ROOTS)
    assert len(out) == 1 and out[0]["event_id"] == 1234567890


def test_non_http_source_url_dropped():
    # href로 렌더링되므로 javascript: 등 비-http 스킴은 저장 단계에서 차단
    e = normalize_export([row({60: "javascript:alert(1)"})], roots=ROOTS)[0]
    assert e["source_url"] is None
    e2 = normalize_export([row({60: "https://ok.example/a"})], roots=ROOTS)[0]
    assert e2["source_url"] == "https://ok.example/a"


def test_missing_actors_and_numbers_become_none():
    e = normalize_export([row({6: "", 16: " ", 30: "", 34: ""})], roots=ROOTS)[0]
    assert e["actor1"] is None and e["actor2"] is None
    assert e["goldstein"] is None and e["tone"] is None

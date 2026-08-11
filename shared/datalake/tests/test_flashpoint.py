import io
import zipfile

import httpx
import pytest

from datalake.sources import flashpoint


def _row(event_id="1001", root="19", lat="26.5", lon="52.0", **over):
    c = [""] * 61
    c[0] = event_id          # GLOBALEVENTID
    c[1] = "20260811"        # SQLDATE
    c[6] = "IRN"             # Actor1
    c[16] = "USA"            # Actor2
    c[26] = "190"            # EventCode
    c[28] = root             # EventRootCode
    c[29] = "4"              # QuadClass
    c[30] = "-10.0"          # GoldsteinScale
    c[31] = "5"              # NumMentions
    c[33] = "3"              # NumArticles
    c[34] = "-7.5"           # AvgTone
    c[53] = "IR"             # ActionGeo_CountryCode
    c[56] = lat              # ActionGeo_Lat
    c[57] = lon              # ActionGeo_Long
    c[59] = "20260811063000"  # DATEADDED
    c[60] = "https://ex.com/article"  # SOURCEURL
    for idx, val in over.items():
        c[int(idx)] = val
    return "\t".join(c)


def _zip_bytes(csv_text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("20260811063000.export.CSV", csv_text)
    return buf.getvalue()


LASTUPDATE = (
    "123 abc http://data.gdeltproject.org/gdeltv2/20260811063000.export.CSV.zip\n"
    "456 def http://data.gdeltproject.org/gdeltv2/20260811063000.mentions.CSV.zip\n"
)


def test_pick_export_url():
    url = flashpoint.pick_export_url(LASTUPDATE)
    assert url.endswith("20260811063000.export.CSV.zip")


def test_pick_export_url_rejects_foreign_host():
    evil = "1 a http://evil.example/x.export.CSV.zip\n"
    with pytest.raises(ValueError):
        flashpoint.pick_export_url(evil)  # SSRF 가드 (hub와 동일)


def test_normalize_filters_and_defends():
    lines = [
        _row(),                                  # 정상 (root 19 교전)
        _row(event_id="1002", root="01"),        # 루트코드 필터 밖
        _row(event_id="1003", lat="", lon=""),   # 좌표 없음 → 스킵
        _row(event_id="bad-id"),                 # id 비정상 → 스킵
        "junk\trow",                             # 기형 행 → 격리
    ]
    rows = flashpoint.normalize(lines)
    assert len(rows) == 1
    e = rows[0]
    assert e["event_id"] == 1001 and e["root"] == "19"
    assert e["goldstein"] == -10.0 and e["tone"] == -7.5
    assert e["lat"] == 26.5 and e["lon"] == 52.0
    assert e["source_url"] == "https://ex.com/article"
    assert e["ts"] == 1786429800.0  # 2026-08-11T06:30:00Z


def test_normalize_blocks_bad_url_scheme():
    (e,) = flashpoint.normalize([_row(**{"60": "javascript:alert(1)"})])
    assert e["source_url"] is None


async def test_fetch_dedups_same_file_across_runs(tmp_path):
    csv_zip = _zip_bytes(_row() + "\n")
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if str(request.url).endswith("lastupdate.txt"):
            return httpx.Response(200, text=LASTUPDATE)
        return httpx.Response(200, content=csv_zip)

    state = tmp_path / "state" / "flashpoint_last_url"
    transport = httpx.MockTransport(handler)

    client = flashpoint.FlashpointClient(transport=transport, state_path=state)
    (rec,) = await client.fetch()
    assert rec.source == "flashpoint" and rec.kind == "export"
    assert rec.payload.startswith("1001\t")  # 전체 CSV 원문 (필터 전)
    assert rec.meta["url"].endswith(".export.CSV.zip")
    assert rec.meta["lines"] == 1

    # 같은 파일 URL 재등장 → 빈 배치, zip 재다운로드 없음 —
    # 새 인스턴스(one-shot 재실행)에서도 상태 파일로 이어진다
    fresh = flashpoint.FlashpointClient(transport=transport, state_path=state)
    n_before = len(calls)
    assert await fresh.fetch() == []
    assert len(calls) == n_before + 1  # lastupdate.txt만 재조회

    # --force는 상태를 무시하고 재수집
    (again,) = await fresh.fetch(force=True)
    assert again.kind == "export"


async def test_fetch_zip_too_large():
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("lastupdate.txt"):
            return httpx.Response(200, text=LASTUPDATE)
        return httpx.Response(200, content=b"x" * (flashpoint.MAX_ZIP_BYTES + 1))

    client = flashpoint.FlashpointClient(transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError, match="zip too large"):
        await client.fetch()


def test_transform_applies_root_filter():
    from datalake.core.source import Record
    from datalake.core.transform import rows_for

    rec = Record(source="flashpoint", kind="export",
                 payload=_row() + "\n" + _row(event_id="1002", root="01"),
                 meta={}, fetched_at=1786429800.0)
    tables = rows_for(rec)
    events = tables["flashpoint_events"]
    assert [e["event_id"] for e in events] == [1001]  # 루트 필터 밖(01) 제외 (hub 동형)
    assert events[0]["country"] == "IR"

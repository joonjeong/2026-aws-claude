import io
import json
import zipfile

import httpx
import pytest

from datalake import gdelt


def _row(event_id="1001", root="19", lat="26.5", lon="52.0", **over):
    c = [""] * 61
    c[0] = event_id
    c[1] = "20260811"
    c[6] = "IRN"
    c[16] = "USA"
    c[26] = "190"
    c[28] = root
    c[29] = "4"
    c[30] = "-10.0"
    c[31] = "5"
    c[33] = "3"
    c[34] = "-7.5"
    c[53] = "IR"
    c[56] = lat
    c[57] = lon
    c[59] = "20260811063000"
    c[60] = "https://ex.com/article"
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


def test_pick_export_url_and_ssrf_guard():
    assert gdelt.pick_export_url(LASTUPDATE).endswith("063000.export.CSV.zip")
    with pytest.raises(ValueError):
        gdelt.pick_export_url("1 a http://evil.example/x.export.CSV.zip\n")


def test_parse_filters_and_defends():
    rows = gdelt.parse("\n".join([
        _row(),                                  # 정상 (root 19 교전)
        _row(event_id="1002", root="01"),        # CAMEO 필터 밖
        _row(event_id="1003", lat="", lon=""),   # 좌표 없음 → 필터
        _row(event_id="bad-id"),                 # id 비정상 → 필터
        "junk\trow",                             # 기형 행 → 격리
    ]))
    assert [e["event_id"] for e in rows] == [1001]
    e = rows[0]
    assert e["root"] == "19" and e["goldstein"] == -10.0
    assert e["ts"] == 1786429800.0  # 2026-08-11T06:30:00Z
    assert e["source_url"] == "https://ex.com/article"


def test_parse_blocks_bad_url_scheme():
    (e,) = gdelt.parse(_row(**{"60": "javascript:alert(1)"}))
    assert e["source_url"] is None


async def test_collect_dedups_across_runs_and_lands(tmp_path):
    csv_zip = _zip_bytes(_row() + "\n" + _row(event_id="1002", root="01"))
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if str(request.url).endswith("lastupdate.txt"):
            return httpx.Response(200, text=LASTUPDATE)
        return httpx.Response(200, content=csv_zip)

    transport = httpx.MockTransport(handler)
    assert await gdelt.collect(tmp_path, transport=transport) == 0

    (landing,) = list(tmp_path.glob("landing/gdelt/flashpoint/dt=*/part-*.jsonl"))
    env = json.loads(landing.read_text())
    assert env["payload"].startswith("1001\t")   # CAMEO 필터 전 전문 보존
    assert "1002\t" in env["payload"]

    (bronze,) = list(tmp_path.glob("bronze/flashpoint_events/source=*/dt=*/part-*.jsonl"))
    rows = [json.loads(x) for x in bronze.read_text().splitlines()]
    assert [r["event_id"] for r in rows] == [1001]  # bronze만 필터 적용

    # 같은 파일 재등장 → 빈 배치 (one-shot 재실행 간에도 상태 파일로 이어짐)
    n_before = len(calls)
    assert await gdelt.collect(tmp_path, transport=transport) == 0
    assert len(calls) == n_before + 1  # lastupdate.txt만 재조회

    # --force는 상태 무시
    await gdelt.collect(tmp_path, force=True, transport=transport)
    assert len(landing.read_text().splitlines()) == 2


async def test_collect_zip_too_large(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("lastupdate.txt"):
            return httpx.Response(200, text=LASTUPDATE)
        return httpx.Response(200, content=b"x" * (gdelt.MAX_ZIP_BYTES + 1))

    with pytest.raises(ValueError, match="zip too large"):
        await gdelt.collect(tmp_path, transport=httpx.MockTransport(handler))

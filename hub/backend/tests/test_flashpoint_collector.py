"""lastupdate.txt 파싱 — export.CSV.zip URL 선택."""
import pytest

from app.modules.flashpoint.collector import pick_export_url

LASTUPDATE = """66203 c7d699 http://data.gdeltproject.org/gdeltv2/20260811064500.export.CSV.zip
72715 a883c6 http://data.gdeltproject.org/gdeltv2/20260811064500.mentions.CSV.zip
3590534 ed0805 http://data.gdeltproject.org/gdeltv2/20260811064500.gkg.csv.zip"""


def test_pick_export_url_selects_export_line():
    url = pick_export_url(LASTUPDATE)
    assert url == "http://data.gdeltproject.org/gdeltv2/20260811064500.export.CSV.zip"


def test_pick_export_url_missing_raises():
    with pytest.raises(ValueError):
        pick_export_url("no export here\nfoo bar")


def test_pick_export_url_rejects_foreign_host():
    # lastupdate.txt는 평문 HTTP — 오염 시 임의 호스트로 GET(SSRF) 방지
    with pytest.raises(ValueError):
        pick_export_url("1 x http://evil.example/steal.export.CSV.zip")


def test_unzip_rejects_oversized_payload():
    import io
    import zipfile

    from app.modules.flashpoint.collector import _unzip_lines

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a.CSV", "x" * 1024)
    with pytest.raises(ValueError):
        _unzip_lines(buf.getvalue(), max_csv_bytes=100)  # 압축해제 상한 초과

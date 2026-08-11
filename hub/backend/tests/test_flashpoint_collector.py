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

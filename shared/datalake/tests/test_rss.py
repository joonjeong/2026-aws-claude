import json

import httpx
import pytest

from datalake import rss


def _rss(items: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>t</title>{items}</channel></rss>"""


def _item(link="https://ex.com/a", title="Hello", pub="Mon, 10 Aug 2026 01:00:00 GMT",
          summary="<p>Sum&amp;mary</p>"):
    return (f"<item><link>{link}</link><title>{title}</title>"
            f"<pubDate>{pub}</pubDate><description>{summary}</description></item>")


def test_feeds_are_15():
    feeds = rss.load_feeds()
    assert len(feeds) == 15
    assert set(feeds) >= {"bbc", "yna", "wapo", "mk", "nyt"}
    assert "Mozilla/5.0" in feeds["wapo"]["user_agent"]  # UA 차단 매체 오버라이드


def test_feeds_file_override(tmp_path, monkeypatch):
    custom = tmp_path / "feeds.toml"
    custom.write_text('[feeds.example]\nname = "Example"\nlang = "en"\n'
                      'rss_url = "https://example.com/rss"\n', encoding="utf-8")
    monkeypatch.setenv("DATALAKE_RSS_FEEDS", str(custom))
    assert set(rss.load_feeds()) == {"example"}  # 목록 파일 교체로 대상 관리


def test_parse_strips_html_and_filters_schemes():
    xml = _rss(
        _item(summary="<b>bold</b> &amp; <i>x</i>  y")
        + _item(link="javascript:alert(1)", title="evil")   # 스킴 차단
        + _item(link="https://ex.com/b", title="<i>Tag</i>gy",
                pub="Tue, 11 Aug 2026 01:00:00 GMT")
    )
    rows = rss.parse("bbc", xml)
    assert [r["link"] for r in rows] == ["https://ex.com/b", "https://ex.com/a"]  # 최신순
    assert rows[1]["summary"] == "bold & x y"
    assert rows[0]["title"] == "Tag gy"  # 태그는 공백 치환 후 압축 (hub 동작)
    assert rows[0]["source"] == "bbc"
    assert rows[0]["published"] == "2026-08-11T01:00:00Z"


def test_parse_caps_latest_15():
    items = "".join(_item(link=f"https://ex.com/{i}", title=f"t{i}",
                          pub=f"Mon, 10 Aug 2026 {i:02d}:00:00 GMT")
                    for i in range(17))
    rows = rss.parse("bbc", _rss(items))
    assert len(rows) == 15 and rows[0]["link"] == "https://ex.com/16"


def test_parse_summary_cap_300():
    rows = rss.parse("bbc", _rss(_item(summary="x" * 500)))
    assert len(rows[0]["summary"]) == 300


async def test_collect_selected_feeds_isolation_and_zones(tmp_path):
    seen_ua = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_ua[request.url.host] = request.headers["user-agent"]
        if "bbci" in str(request.url):
            return httpx.Response(503)  # bbc 실패 → 격리
        return httpx.Response(200, text=_rss(_item()))

    assert await rss.collect(tmp_path, ["bbc", "npr", "wapo"],
                             transport=httpx.MockTransport(handler)) == 0

    # bbc 실패는 격리 — npr·wapo만 랜딩
    landed = {p.parts[-4] for p in tmp_path.glob("landing/*/news/dt=*/part-*.jsonl")}
    assert landed == {"npr", "wapo"}

    # 매체(공급자)별로 파티션 분리 — source=npr / source=wapo 두 파일
    parts = sorted(tmp_path.glob("bronze/news_articles/source=*/dt=*/part-*.jsonl"))
    assert [p.parts[-3] for p in parts] == ["source=npr", "source=wapo"]
    rows = [json.loads(x) for p in parts for x in p.read_text().splitlines()]
    assert {r["source"] for r in rows} == {"npr", "wapo"}
    assert all("first_seen" in r for r in rows)

    uas = list(seen_ua.values())
    assert any(ua.startswith("DataLake/0.1") for ua in uas)
    assert any(ua.startswith("Mozilla/5.0") for ua in uas)  # wapo 오버라이드


async def test_collect_unknown_feed_raises(tmp_path):
    with pytest.raises(ValueError):
        await rss.collect(tmp_path, ["bbc", "nope"])

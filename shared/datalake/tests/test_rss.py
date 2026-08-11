import httpx
import pytest

from datalake.sources import rss


def _rss(items: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>t</title>{items}</channel></rss>"""


def _item(link="https://ex.com/a", title="Hello", pub="Mon, 10 Aug 2026 01:00:00 GMT",
          summary="<p>Sum&amp;mary</p>"):
    return (f"<item><link>{link}</link><title>{title}</title>"
            f"<pubDate>{pub}</pubDate><description>{summary}</description></item>")


def test_feeds_are_15():
    assert len(rss.FEEDS) == 15
    assert set(rss.FEEDS) >= {"bbc", "yna", "wapo", "mk", "nyt"}
    # WaPo는 브라우저 UA 오버라이드 필수 (비브라우저 UA 403)
    assert "Mozilla/5.0" in rss.FEEDS["wapo"]["user_agent"]


def test_unknown_feed_rejected():
    with pytest.raises(ValueError):
        rss.RssClient("nope")


def test_normalize_strips_html_and_filters_schemes():
    xml = _rss(
        _item(summary="<b>bold</b> &amp; <i>x</i>  y")
        + _item(link="javascript:alert(1)", title="evil")   # 스킴 차단
        + _item(link="https://ex.com/b", title="<i>Tag</i>gy",
                pub="Tue, 11 Aug 2026 01:00:00 GMT")
    )
    rows = rss.normalize("bbc", xml)
    assert [r["link"] for r in rows] == ["https://ex.com/b", "https://ex.com/a"]  # 최신순
    assert rows[1]["summary"] == "bold & x y"
    assert rows[0]["title"] == "Tag gy"  # 태그는 공백 치환 후 압축 (hub 동작)
    assert rows[0]["source"] == "bbc"
    assert rows[0]["published"] == "2026-08-11T01:00:00Z"


def test_normalize_caps_latest_15():
    items = "".join(
        _item(link=f"https://ex.com/{i}", title=f"t{i}",
              pub=f"Mon, 10 Aug 2026 {i:02d}:00:00 GMT")
        for i in range(17)
    )
    rows = rss.normalize("bbc", _rss(items))
    assert len(rows) == 15
    assert rows[0]["link"] == "https://ex.com/16"


def test_normalize_summary_cap_300():
    rows = rss.normalize("bbc", _rss(_item(summary="x" * 500)))
    assert len(rows[0]["summary"]) == 300


async def test_fetch_source_is_feed_and_kind_is_news():
    seen_ua = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_ua[str(request.url)] = request.headers["user-agent"]
        return httpx.Response(200, text=_rss(_item()))

    transport = httpx.MockTransport(handler)

    (rec,) = await rss.RssClient("bbc", transport=transport).fetch()
    assert rec.source == "bbc" and rec.kind == "news"
    assert rec.payload.startswith("<?xml")
    assert rec.meta["status"] == 200

    (rec_wapo,) = await rss.RssClient("wapo", transport=transport).fetch()
    assert rec_wapo.source == "wapo" and rec_wapo.kind == "news"

    uas = list(seen_ua.values())
    assert any(ua.startswith("DataLake/0.1") for ua in uas)
    assert any(ua.startswith("Mozilla/5.0") for ua in uas)  # wapo 오버라이드


async def test_fetch_all_isolates_feed_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        if "bbci" in str(request.url):
            return httpx.Response(503)
        return httpx.Response(200, text=_rss(_item()))

    records = await rss.fetch_all(["bbc", "npr"],
                                  transport=httpx.MockTransport(handler))
    assert [r.source for r in records] == ["npr"]  # bbc 실패가 npr을 못 죽임


async def test_fetch_all_unknown_feed_raises():
    with pytest.raises(ValueError):
        await rss.fetch_all(["bbc", "nope"])


def test_feeds_file_override(tmp_path, monkeypatch):
    custom = tmp_path / "feeds.toml"
    custom.write_text(
        '[feeds.example]\nname = "Example"\nlang = "en"\n'
        'rss_url = "https://example.com/rss"\n', encoding="utf-8")
    monkeypatch.setenv("DATALAKE_RSS_FEEDS", str(custom))
    feeds = rss._load_feeds()
    assert set(feeds) == {"example"}  # 목록 파일 교체로 대상 관리

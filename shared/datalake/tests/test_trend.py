import json

import httpx
import pytest

from datalake.sources import trend


def _item(vid="v1", views="100", likes="5"):
    return {
        "id": vid,
        "snippet": {
            "title": "T", "channelTitle": "C", "categoryId": "10",
            "thumbnails": {"medium": {"url": "https://img/m.jpg"}},
            "publishedAt": "2026-08-10T00:00:00Z",
        },
        "statistics": {"viewCount": views, "likeCount": likes},
    }


def test_normalize_items():
    payload = {"items": [_item(), _item(vid="v2", views="abc", likes="-3"), "junk"]}
    rows = trend.normalize(payload)
    assert len(rows) == 2  # 깨진 항목 격리
    assert rows[0] == {
        "video_id": "v1", "title": "T", "channel": "C", "category_id": "10",
        "thumbnail": "https://img/m.jpg", "view_count": 100, "like_count": 5,
        "published_at": "2026-08-10T00:00:00Z",
    }
    assert rows[1]["view_count"] == 0 and rows[1]["like_count"] == 0  # 문자열/음수 방어


def test_build_disabled_without_key(monkeypatch):
    monkeypatch.delenv("YT_API_KEY", raising=False)
    assert trend.build() is None


async def test_fetch_key_never_leaks(monkeypatch):
    monkeypatch.setenv("YT_API_KEY", "SECRETKEY")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["key"] == "SECRETKEY"
        assert request.url.params["chart"] == "mostPopular"
        assert request.url.params["regionCode"] == "KR"
        assert request.url.params["maxResults"] == "30"
        return httpx.Response(200, json={"items": [_item()]})

    src = trend.TrendSource(transport=httpx.MockTransport(handler))
    (job,) = src.jobs()
    assert job.name == "trend-youtube"
    assert job.interval_s == 60.0  # hub POLL_INTERVAL_S

    (rec,) = await job.fetch()
    assert rec.source == "trend" and rec.kind == "trending"
    assert rec.payload["items"][0]["id"] == "v1"
    assert "SECRETKEY" not in json.dumps(rec.meta)  # 키 비노출


async def test_fetch_upstream_error_no_body_in_exception(monkeypatch):
    monkeypatch.setenv("YT_API_KEY", "SECRETKEY")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "quota SECRET details"})

    src = trend.TrendSource(transport=httpx.MockTransport(handler))
    (job,) = src.jobs()
    with pytest.raises(RuntimeError) as exc_info:
        await job.fetch()
    assert "403" in str(exc_info.value)
    assert "SECRET" not in str(exc_info.value)  # 본문은 로그로만

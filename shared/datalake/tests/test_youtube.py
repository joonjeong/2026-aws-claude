import json

import httpx
import pytest

from datalake import youtube


def _item(vid="v1", views="100", likes="5"):
    return {
        "id": vid,
        "snippet": {"title": "T", "channelTitle": "C", "categoryId": "10",
                    "thumbnails": {"medium": {"url": "https://img/m.jpg"}},
                    "publishedAt": "2026-08-10T00:00:00Z"},
        "statistics": {"viewCount": views, "likeCount": likes},
    }


def test_parse_items():
    rows = youtube.parse({"items": [_item(), _item(vid="v2", views="abc", likes="-3"),
                                    "junk"]})
    assert len(rows) == 2  # 깨진 항목 격리
    assert rows[0]["video_id"] == "v1" and rows[0]["view_count"] == 100
    assert rows[1]["view_count"] == 0 and rows[1]["like_count"] == 0  # 방어


async def test_collect_key_never_leaks_and_lands(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["key"] == "SECRETKEY"
        assert request.url.params["chart"] == "mostPopular"
        return httpx.Response(200, json={"items": [_item()]})

    assert await youtube.collect(tmp_path, "SECRETKEY", keep_landing=True,
                                 transport=httpx.MockTransport(handler)) == 0

    (landing,) = list(tmp_path.glob("landing/youtube/trend/dt=*/part-*.jsonl"))
    env = json.loads(landing.read_text())
    assert "SECRETKEY" not in json.dumps(env["meta"])  # 키 비노출

    (videos,) = list(tmp_path.glob("bronze/trend_videos/source=*/dt=*/part-*.jsonl"))
    (stats,) = list(tmp_path.glob("bronze/trend_video_stats/source=*/dt=*/part-*.jsonl"))
    (v,) = [json.loads(x) for x in videos.read_text().splitlines()]
    (s,) = [json.loads(x) for x in stats.read_text().splitlines()]
    assert v["video_id"] == "v1" and "first_seen" in v
    assert s["rank"] == 1 and s["ts"] % youtube.BUCKET_S == 0  # 버킷 정렬값


async def test_collect_upstream_error_no_body_in_exception(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "quota SECRET details"})

    with pytest.raises(RuntimeError) as exc_info:
        await youtube.collect(tmp_path, "SECRETKEY",
                              transport=httpx.MockTransport(handler))
    assert "403" in str(exc_info.value)
    assert "SECRET" not in str(exc_info.value)  # 본문은 로그로만

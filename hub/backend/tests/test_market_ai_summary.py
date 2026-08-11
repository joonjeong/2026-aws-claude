"""AI 시황 요약 — 5분 버킷 캐시 재생과 프롬프트 구성 계약."""
import json

from app.modules.market.services import ai


def _parse_frames(raw: list[str]) -> list[tuple[str, dict]]:
    out = []
    for frame in raw:
        event, data = None, None
        for line in frame.strip().split("\n"):
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        out.append((event, data))
    return out


async def test_cached_bucket_replays_without_bedrock(monkeypatch):
    ai._summary_cache.update(bucket=ai.summary_bucket(), text="캐시된 요약")

    def boom(*a, **k):  # 캐시 히트면 Bedrock 클라이언트를 만들 일이 없어야 한다
        raise AssertionError("bedrock must not be called on cache hit")

    monkeypatch.setattr(ai, "_get_client", boom)
    frames = _parse_frames([f async for f in ai.market_summary_stream({}, [], [])])
    assert frames[0] == ("phase", {"phase": "cached"})
    assert frames[1][0] == "final"
    assert frames[1][1] == {"text": "캐시된 요약", "cached": True}


def test_summary_bucket_is_5min_by_default():
    assert ai.summary_bucket(1200.0) == ai.summary_bucket(1499.9)
    assert ai.summary_bucket(1200.0) != ai.summary_bucket(1500.0)


def test_market_prompt_includes_indices_indicators_and_movers():
    overview = {
        "indices": [{"name": "S&P 500", "price": 7753.11, "change_pct": -0.06}],
        "indicators": [{"name": "WTI유", "price": 82.51, "change_pct": 0.46}],
    }
    us = [  # 6종목 — 상승/하락 상위 3이 겹치지 않게
        {"name": "Apple", "price": 308.26, "change_pct": -1.62},
        {"name": "NVIDIA", "price": 217.55, "change_pct": -2.86},
        {"name": "Microsoft", "price": 506.06, "change_pct": 1.21},
        {"name": "Amazon", "price": 278.09, "change_pct": 1.32},
        {"name": "Meta", "price": 594.92, "change_pct": 0.48},
        {"name": "Tesla", "price": 330.88, "change_pct": 0.7},
    ]
    kr = [{"name": "삼성전자", "price": 91000, "change_pct": 0.9}]
    p = ai.market_prompt(overview, us, kr)
    assert "S&P 500" in p and "WTI유" in p and "삼성전자" in p
    # 상승 상위는 +% 부호, 하락 상위는 내림차순 정렬 확인
    assert "Microsoft: 506.06 (+1.21%)" in p
    assert p.index("NVIDIA") > p.index("하락 상위")

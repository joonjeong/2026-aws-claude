"""Korean trend briefing via labkit.bedrock (Converse REST, no SDK).

Cache: labkit.bedrock.BucketCachedText(POLL_INTERVAL_S) keyed by mode —
"cache for the same time bucket" per spec. Error contract is labkit's:
token env missing -> BedrockError(503); upstream/timeout/parse ->
BedrockError(502) with status code only (bodies stay in the log).
"""
from __future__ import annotations

from typing import Any

from labkit.bedrock import BucketCachedText

from .. import config

_cache = BucketCachedText(bucket_s=config.POLL_INTERVAL_S)

SYSTEM_PROMPT = (
    "당신은 한국 유튜브 트렌드 분석가입니다. 급상승 동영상 목록을 바탕으로 "
    "한국어 브리핑을 작성합니다. 반드시 다음 구성을 지키세요:\n"
    "1) 주제 클러스터 3~4개 — 각 클러스터가 왜 뜨는지 한두 문장씩\n"
    "2) 카테고리 분포에서 읽히는 흐름 한 단락\n"
    "3) 제작/시청 관점 인사이트 2~3줄\n"
    "간결하고 구체적으로, 마크다운 목록을 활용해 작성하세요."
)


def _fmt_views(n: int) -> str:
    if n >= 100_000_000:
        return f"{n / 100_000_000:.1f}억"
    if n >= 10_000:
        return f"{n / 10_000:.1f}만"
    return str(n)


def _summarize_items(
    items: list[dict[str, Any]], category_names: dict[str, str], limit: int = 30
) -> str:
    lines = []
    for i, it in enumerate(items[:limit], start=1):
        name = category_names.get(it["category_id"], it["category_id"])
        lines.append(
            f"{i}. [{name}] {it['title']} — {it['channel']} "
            f"(조회수 {_fmt_views(it['view_count'])})"
        )
    return "\n".join(lines)


def _shares_line(items: list[dict[str, Any]], category_names: dict[str, str]) -> str:
    from ..derive.trends import category_shares

    shares = category_shares(items, category_names)
    ranked = sorted(shares.items(), key=lambda kv: kv[1], reverse=True)
    return ", ".join(f"{name} {share:.0%}" for name, share in ranked)


def build_user_text(
    mode: str,
    latest: dict[str, Any],
    previous: dict[str, Any] | None,
    category_names: dict[str, str],
) -> str:
    latest_items = latest.get("items", [])
    parts = [
        f"[현재 급상승 30 — 수집 시각 {latest.get('captured_at')}]",
        _summarize_items(latest_items, category_names),
        f"\n카테고리 분포: {_shares_line(latest_items, category_names)}",
    ]
    if mode == "daily" and previous is not None:
        prev_items = previous.get("items", [])
        latest_ids = {it["video_id"] for it in latest_items}
        prev_ids = {it["video_id"] for it in prev_items}
        new_titles = [it["title"] for it in latest_items
                      if it["video_id"] not in prev_ids]
        exited_titles = [it["title"] for it in prev_items
                         if it["video_id"] not in latest_ids]
        parts += [
            f"\n[기준선 스냅샷 — 수집 시각 {previous.get('captured_at')}]",
            _summarize_items(prev_items, category_names),
            f"\n기준선 카테고리 분포: {_shares_line(prev_items, category_names)}",
            f"\n신규 진입 {len(new_titles)}건: " + "; ".join(new_titles[:10]),
            f"이탈 {len(exited_titles)}건: " + "; ".join(exited_titles[:10]),
            "\n기준선 대비 무엇이 바뀌었는지 중심으로 비교 브리핑을 작성하세요.",
        ]
    else:
        parts.append("\n현재 스냅샷을 요약하는 브리핑을 작성하세요.")
    return "\n".join(parts)


async def generate(
    mode: str,
    latest: dict[str, Any],
    previous: dict[str, Any] | None,
    category_names: dict[str, str],
) -> tuple[str, bool, int]:
    """Returns (brief text, cached, bucket). Raises labkit BedrockError."""
    return await _cache.generate(
        key=mode,
        system=SYSTEM_PROMPT,
        user_text=build_user_text(mode, latest, previous, category_names),
        max_tokens=config.BRIEF_MAX_TOKENS,
    )

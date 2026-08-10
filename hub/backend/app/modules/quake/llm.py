"""Korean earthquake briefing via labkit Bedrock converse, 10-min bucket cache.

Error contract lives in labkit.bedrock: missing token -> BedrockError(503),
upstream failure -> BedrockError(502, status code only). api.py maps those
to HTTP responses.
"""
from __future__ import annotations

from datetime import datetime, timezone

from labkit import BucketCachedText

from . import config

_cache = BucketCachedText(config.BRIEF_BUCKET_S)

SYSTEM_PROMPT = (
    "당신은 지진 활동 브리핑 전문가입니다. 주어진 최근 24시간 지진 데이터를 바탕으로 "
    "반드시 \"지난 24시간, 지구는\"으로 시작하는 한국어 브리핑을 작성하세요. 구성: "
    "(1) 전체 흐름을 요약하는 한 문단, (2) 주목할 이벤트 2~3개에 대한 간단한 해설, "
    "(3) 활동이 급증한 지역 언급. 과장 없이 담백하게, 수치는 데이터에 있는 것만 사용하세요."
)


def _fmt_utc(ms: int) -> str:
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M UTC"
        )
    except (OverflowError, OSError, ValueError):
        return "unknown"


def build_user_text(stats: dict, top_events: list[dict]) -> str:
    lines = [
        "[최근 24시간 요약 통계]",
        f"- 총 건수: {stats['count']}",
        f"- 최대 규모: M{stats['max_mag']}",
        f"- 활동 최다 지역: {stats['top_region'] or 'unknown'}",
        "",
        "[규모순 상위 이벤트]",
    ]
    for e in top_events:
        lines.append(
            f"- M{e['mag']} | {e['place']} | 깊이 {e['depth_km']}km | {_fmt_utc(e['time'])}"
        )
    if not top_events:
        lines.append("- (이벤트 없음)")
    return "\n".join(lines)


async def generate_brief(stats: dict, top_events: list[dict]) -> tuple[str, bool, int]:
    """Returns (brief_text, cached, bucket). Raises labkit BedrockError."""
    return await _cache.generate(
        system=SYSTEM_PROMPT,
        user_text=build_user_text(stats, top_events),
        max_tokens=config.BRIEF_MAX_TOKENS,
    )

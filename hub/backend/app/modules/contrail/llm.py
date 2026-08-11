"""항공 교통 한국어 브리핑 — quake llm.py 패턴 (10분 버킷 캐시)."""
from __future__ import annotations

from labkit import BucketCachedText

from . import config

_cache = BucketCachedText(config.BRIEF_BUCKET_S)

SYSTEM_PROMPT = (
    "당신은 항공 교통 브리핑 전문가입니다. 주어진 전 세계·관심지역 최근 6시간 항공 "
    "데이터를 바탕으로 반드시 \"지난 6시간, 하늘은\"으로 시작하는 한국어 브리핑을 "
    "작성하세요. 구성: (1) 전 세계 규모 요약 한 문단, (2) 관심지역 흐름과 주목할 "
    "항공기 2~3대 해설, (3) 특징적인 패턴. 과장 없이 담백하게, 수치는 데이터에 "
    "있는 것만 사용하세요."
)


def build_user_text(global_stats: dict, region_stats: dict,
                    preset_label: str, notable: list[dict]) -> str:
    lines = [
        "[전 세계 스냅샷]",
        f"- 추적 항공기: {global_stats['count']}대 (공중 {global_stats['airborne']}대)",
        f"- 최다 등록 국가: {global_stats['top_country'] or 'unknown'}",
        "",
        f"[관심지역: {preset_label} — 최근 6시간]",
        f"- 관측 항공기: {region_stats['count']}대",
        "",
        "[속도순 상위 항공기]",
    ]
    for f in notable:
        lines.append(
            f"- {f.get('callsign') or f['id']} | {f.get('origin_country') or '?'}"
            f" | 고도 {round((f.get('alt_m') or 0))}m"
            f" | {round((f.get('velocity_ms') or 0) * 3.6)}km/h"
        )
    if not notable:
        lines.append("- (관측 항공기 없음 — 수집 초기 상태)")
    return "\n".join(lines)


async def generate_brief(global_stats: dict, region_stats: dict,
                         preset_label: str, notable: list[dict]) -> tuple[str, bool, int]:
    """Returns (text, cached, bucket). Raises labkit BedrockError (503/502)."""
    return await _cache.generate(
        key=preset_label,
        system=SYSTEM_PROMPT,
        user_text=build_user_text(global_stats, region_stats, preset_label, notable),
        max_tokens=config.BRIEF_MAX_TOKENS,
    )

"""해상 교통 한국어 브리핑 — quake llm.py 패턴 (10분 버킷 캐시)."""
from __future__ import annotations

from labkit import BucketCachedText

from . import config

_cache = BucketCachedText(config.BRIEF_BUCKET_S)

SYSTEM_PROMPT = (
    "당신은 해상 교통 브리핑 전문가입니다. 주어진 관심 해역의 최근 6시간 선박 "
    "데이터를 바탕으로 반드시 \"지난 6시간, 바다는\"으로 시작하는 한국어 브리핑을 "
    "작성하세요. 구성: (1) 해역 전체 흐름 한 문단, (2) 주목할 선박 2~3척 간단 해설, "
    "(3) 선종 구성의 특징. 과장 없이 담백하게, 수치는 데이터에 있는 것만 사용하세요."
)


def build_user_text(stats: dict, preset_label: str, notable: list[dict]) -> str:
    lines = [
        f"[관심 해역: {preset_label} — 최근 6시간 요약]",
        f"- 관측 선박: {stats['count']}척 (이동 중 {stats['moving']}척)",
        f"- 최다 선종: {stats['top_type'] or 'unknown'}",
        f"- 최고 속력: {stats['max_sog'] or 0}kn",
        "",
        "[속력순 상위 선박]",
    ]
    for v in notable:
        lines.append(
            f"- {v.get('name') or 'MMSI ' + v['id']} | {v.get('ship_type') or '기타'}"
            f" | {v.get('sog_kn') or 0}kn | 침로 {v.get('cog_deg') or '?'}°"
        )
    if not notable:
        lines.append("- (관측 선박 없음 — AIS 키 미설정 또는 수집 초기 상태)")
    return "\n".join(lines)


async def generate_brief(stats: dict, preset_label: str,
                         notable: list[dict]) -> tuple[str, bool, int]:
    """Returns (text, cached, bucket). Raises labkit BedrockError (503/502)."""
    return await _cache.generate(
        key=preset_label,  # 프리셋별 캐시 슬롯
        system=SYSTEM_PROMPT,
        user_text=build_user_text(stats, preset_label, notable),
        max_tokens=config.BRIEF_MAX_TOKENS,
    )

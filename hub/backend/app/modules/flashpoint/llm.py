"""분쟁·불안 정세 한국어 브리핑 — quake llm.py 패턴 (10분 버킷 캐시)."""
from __future__ import annotations

from datetime import datetime, timezone

from labkit import BucketCachedText

from . import config

_cache = BucketCachedText(config.BRIEF_BUCKET_S)

SYSTEM_PROMPT = (
    "당신은 국제 분쟁 정세 브리핑 전문가입니다. 주어진 최근 24시간 GDELT 이벤트 "
    "데이터(뉴스 보도 기반 자동 추출 — 중복·오탐 가능)를 바탕으로 반드시 "
    "\"지난 24시간, 이 지역은\"으로 시작하는 한국어 브리핑을 작성하세요. 구성: "
    "(1) 전체 긴장도 요약 한 문단, (2) 언급이 집중된 이벤트 2~3건 해설, "
    "(3) 유형 분포에서 읽히는 패턴. 보도 기반 데이터의 한계를 감안해 단정 대신 "
    "추정 어조를 유지하고, 수치는 데이터에 있는 것만 사용하세요."
)


def _fmt_utc(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%m-%d %H:%M UTC")
    except (OverflowError, OSError, ValueError):
        return "unknown"


def build_user_text(stats: dict, region_label: str, top_events: list[dict]) -> str:
    by_root = stats.get("by_root") or {}
    root_line = ", ".join(
        f"{config.ROOT_LABELS.get(r, r)} {n}건"
        for r, n in sorted(by_root.items(), key=lambda kv: -kv[1])
    ) or "없음"
    lines = [
        f"[관심지역: {region_label} — 최근 24시간]",
        f"- 이벤트: {stats['count']}건",
        f"- 유형 분포: {root_line}",
        f"- 최다 발생 국가: {stats['top_country'] or 'unknown'}",
        "",
        "[언급 수 상위 이벤트]",
    ]
    for e in top_events:
        label = config.ROOT_LABELS.get(e.get("root"), e.get("root"))
        actors = f"{e.get('actor1') or '?'} → {e.get('actor2') or '?'}"
        lines.append(
            f"- {label} | {actors} | {e.get('country') or '?'}"
            f" | 언급 {e.get('mentions') or 0}회 | {_fmt_utc(e['ts'])}"
        )
    if not top_events:
        lines.append("- (이벤트 없음 — 수집 초기이거나 조용한 상태)")
    return "\n".join(lines)


async def generate_brief(stats: dict, region_label: str,
                         top_events: list[dict]) -> tuple[str, bool, int]:
    """Returns (text, cached, bucket). Raises labkit BedrockError (503/502)."""
    return await _cache.generate(
        key=region_label,
        system=SYSTEM_PROMPT,
        user_text=build_user_text(stats, region_label, top_events),
        max_tokens=config.BRIEF_MAX_TOKENS,
    )

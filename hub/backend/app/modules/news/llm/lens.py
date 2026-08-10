"""The lens — the heart of this capstone.

Bundles the four sources' latest headlines+summaries into one prompt,
calls Bedrock Converse through labkit (httpx REST, Bearer env var only),
enforces a JSON-only output contract, parses code-fence-tolerantly, and
caches per 10-minute bucket (labkit.BucketCachedText).

Error contract (labkit): token env var unset → BedrockError(503);
upstream/timeout → BedrockError(502). JSON contract violations here
also map to 502 (LensParseError).
"""
from __future__ import annotations

import json
import logging
import re

from labkit import BucketCachedText

from .. import config
from ..store.articles import ArticleStore

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
너는 4개 매체(bbc=BBC World, guardian=The Guardian World, nhk=NHK 국제, \
yna=연합뉴스 국제)의 헤드라인을 비교하는 미디어 분석가다.

반드시 아래 스키마의 JSON "하나만" 출력한다. 코드펜스, 설명, 전후 텍스트 금지.

{"clusters":[{"topic":"한국어 토픽명","summary":"공통 사실 2문장",
  "frames":{"bbc":"이 매체의 프레임 1문장","guardian":"...","nhk":"...","yna":"..."},
  "sources":{"bbc":[기사 인덱스],"guardian":[...],"nhk":[...],"yna":[...]}}],
 "overview":"오늘의 미디어 지형 3문장"}

규칙:
- 클러스터는 2개 이상 매체가 다룬 공통 토픽만 3~5개.
- 해당 토픽을 다루지 않은 매체의 frame 값은 정확히 "미보도", sources에서 그 매체는 빈 배열.
- sources의 기사 인덱스는 입력에 표기된 각 매체별 [n] 번호를 그대로 쓴다.
- 모든 생성 텍스트는 한국어로 쓴다.
"""

_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$", re.MULTILINE)


class LensParseError(Exception):
    """The model broke the JSON-only contract → HTTP 502 upstream error."""


def build_user_text(store: ArticleStore) -> str:
    """Headline bundle: per source, the latest headlines with [n] indexes."""
    blocks: list[str] = []
    for source in config.SOURCES:
        lines = [f"## {source['id']} — {source['name']} (lang={source['lang']})"]
        articles = store.latest(source["id"])
        if not articles:
            lines.append("(수집된 기사 없음)")
        for i, a in enumerate(articles):
            summary = f" — {a['summary']}" if a["summary"] else ""
            lines.append(f"[{i}] {a['title']}{summary}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def parse_lens_json(text: str) -> dict:
    """Code-fence-tolerant strict parsing: strip fences / surrounding prose,
    keep the outermost {...}, then json.loads. Contract violation → 502."""
    cleaned = _FENCE_RE.sub("", text).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise LensParseError("no JSON object in lens response")
    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        logger.error("lens JSON parse failed: %s; head=%r", exc, text[:500])
        raise LensParseError("lens response is not valid JSON") from exc
    if not isinstance(data, dict) or "clusters" not in data or "overview" not in data:
        raise LensParseError("lens JSON missing clusters/overview")
    return data


class Lens:
    def __init__(self, store: ArticleStore) -> None:
        self._store = store
        self._cache = BucketCachedText(config.LENS_BUCKET_S)  # 10-min bucket

    async def generate(self) -> dict:
        """→ {"clusters", "overview", "cached", "bucket"}.

        Raises labkit.BedrockError (503 no key / 502 upstream) or
        LensParseError (502). The raw text is what gets bucket-cached, so
        a cached bucket never re-hits Bedrock.
        """
        text, cached, bucket = await self._cache.generate(
            key="lens",
            system=SYSTEM_PROMPT,
            user_text=build_user_text(self._store),
            max_tokens=config.LENS_MAX_TOKENS,
            model=config.LENS_MODEL,
            region=config.LENS_REGION,
        )
        data = parse_lens_json(text)
        return {
            "clusters": data.get("clusters", []),
            "overview": data.get("overview", ""),
            "cached": cached,
            "bucket": bucket,
        }

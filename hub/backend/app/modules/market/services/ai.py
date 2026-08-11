"""AI analysis SSE stream — boto3 bedrock-runtime converse_stream.

Spec mandates boto3 here (labkit.bedrock is NOT used in this project).
Auth: AWS_BEARER_TOKEN_BEDROCK env var only — boto3 picks it up natively;
no credential kwargs on the client. Token unset → HTTP 503 before streaming.
Upstream error bodies are logged server-side; clients see status codes only.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from typing import Any, AsyncIterator, Callable

import boto3

from ..core import config

log = logging.getLogger("market.ai")

_client = None
_client_lock = threading.Lock()


def token_present() -> bool:
    return bool(os.environ.get("AWS_BEARER_TOKEN_BEDROCK"))


def _get_client():
    global _client
    with _client_lock:
        if _client is None:
            # NO credential kwargs — boto3 natively honors AWS_BEARER_TOKEN_BEDROCK
            _client = boto3.client("bedrock-runtime", region_name=config.BEDROCK_REGION)
        return _client


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


_SYSTEM = (
    "너는 한국어로 답하는 주식 시황 애널리스트다. 제공된 시세 데이터만 근거로 "
    "간결한 마크다운으로 다음 세 섹션을 작성한다: "
    "## 기술적 분석, ## 투자 포인트, ## 리스크. "
    "투자 권유가 아닌 정보 제공임을 한 줄로 덧붙인다."
)

_ARTICLE_SYSTEM = (
    "너는 한국어로 답하는 금융 뉴스 애널리스트다. 제공된 기사 정보만 근거로 "
    "간결한 마크다운으로 다음 세 섹션을 작성한다: "
    "## 핵심 요약 (기사가 한국어가 아니면 한국어 번역 요지를 먼저 제시), "
    "## 시장·종목 영향, ## 리스크. "
    "투자 권유가 아닌 정보 제공임을 한 줄로 덧붙인다."
)


_MARKET_SYSTEM = (
    "너는 한국어로 답하는 시황 애널리스트다. 제공된 지수·지표·종목 시세만 근거로 "
    "간결한 마크다운으로 다음 세 섹션을 작성한다: "
    "## 시장 개관, ## 섹터·종목 동향, ## 관전 포인트. "
    "전체 6~10문장 이내로 짧게. 투자 권유가 아닌 정보 제공임을 한 줄로 덧붙인다."
)


def _fmt_rows(rows: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"- {r['name']}: {r['price']} ({'+' if r['change_pct'] >= 0 else ''}{r['change_pct']}%)"
        for r in rows
    )


def market_prompt(overview: dict[str, Any], us: list[dict[str, Any]],
                  kr: list[dict[str, Any]]) -> str:
    """전체 시황 프롬프트 — 지수 5 + 지표 11 + 시장별 상승/하락 상위 3."""
    def movers(rows: list[dict[str, Any]]) -> str:
        by_pct = sorted(rows, key=lambda r: r["change_pct"], reverse=True)
        return (f"상승 상위:\n{_fmt_rows(by_pct[:3])}\n"
                f"하락 상위:\n{_fmt_rows(by_pct[-3:][::-1])}")

    return (
        f"[지수]\n{_fmt_rows(overview.get('indices', []))}\n\n"
        f"[지표 — 원자재·환율·금리·크립토]\n{_fmt_rows(overview.get('indicators', []))}\n\n"
        f"[미국 주요 종목]\n{movers(us)}\n\n"
        f"[한국 주요 종목]\n{movers(kr)}\n\n"
        "위 데이터를 기반으로 현재 전체 시황을 요약하라."
    )


def _user_prompt(detail: dict[str, Any]) -> str:
    return (
        f"종목: {detail['name']} ({detail['symbol']}, {detail['market']})\n"
        f"현재가: {detail['price']} / 등락: {detail['change']} ({detail['change_pct']}%)\n"
        f"거래량: {detail['volume']}\n"
        f"기간 수익률: 1주 {detail['returns']['1w']}% · 1개월 {detail['returns']['1m']}% · "
        f"3개월 {detail['returns']['3m']}% · 1년 {detail['returns']['1y']}%\n"
        f"52주 범위: {detail['week52']['low']} ~ {detail['week52']['high']} "
        f"(현재 위치 {round(detail['week52']['position'] * 100)}%)\n"
        f"기준일: {detail['as_of']}\n"
        "위 데이터를 기반으로 분석하라."
    )


def _stream_worker(system: str, prompt: str, loop: asyncio.AbstractEventLoop,
                   queue: asyncio.Queue) -> None:
    """Blocking converse_stream iteration in a thread; pushes to async queue.

    Never logs prompt/article content — errors carry status codes only."""
    def put(item: tuple[str, Any]) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, item)

    try:
        resp = _get_client().converse_stream(
            modelId=config.BEDROCK_MODEL_ID,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": config.BEDROCK_MAX_TOKENS},
        )
        for event in resp["stream"]:
            delta = event.get("contentBlockDelta", {}).get("delta", {})
            text = delta.get("text")
            if text:
                put(("delta", text))
        put(("done", None))
    except Exception as exc:  # noqa: BLE001
        status = 502
        meta = getattr(exc, "response", None)
        if isinstance(meta, dict):
            status = meta.get("ResponseMetadata", {}).get("HTTPStatusCode", 502)
        log.error("bedrock converse_stream failed (%s): %r", status, exc)  # body server-side only
        put(("error", int(status)))


async def _converse_sse(system: str, prompt: str,
                        on_final: Callable[[str], None] | None = None,
                        ) -> AsyncIterator[str]:
    """Shared SSE machinery: phase(fetching→analyzing) → delta* → final.

    Used by the stock/article analysis and the market summary streams.
    `on_final`: 완성 텍스트 훅 (시황 요약이 버킷 캐시에 저장할 때 사용)."""
    yield _sse("phase", {"phase": "fetching"})
    # inputs are already in hand when this runs; transition immediately
    yield _sse("phase", {"phase": "analyzing"})

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    threading.Thread(target=_stream_worker, args=(system, prompt, loop, queue),
                     daemon=True).start()

    parts: list[str] = []
    while True:
        kind, payload = await queue.get()
        if kind == "delta":
            parts.append(payload)
            yield _sse("delta", {"text": payload})
        elif kind == "error":
            yield _sse("error", {"status": payload})
            return
        else:  # done
            text = "".join(parts)
            if on_final is not None:
                on_final(text)
            yield _sse("final", {"text": text})
            return


def analyze_stream(detail: dict[str, Any]) -> AsyncIterator[str]:
    """Stock analysis SSE stream (detail already fetched by the route)."""
    return _converse_sse(_SYSTEM, _user_prompt(detail))


# ── 전체 시황 요약 — 5분 버킷 캐시 ─────────────────────────────────────
# 같은 버킷의 재요청(수동 refresh 포함)은 Bedrock을 다시 부르지 않고
# 저장된 텍스트를 즉시 final로 재생한다. 최신 버킷 1개만 유지.
_summary_cache: dict[str, Any] = {}  # {"bucket": int, "text": str}


def summary_bucket(now: float | None = None) -> int:
    return int((now if now is not None else time.time()) // config.SUMMARY_BUCKET_S)


async def market_summary_stream(overview: dict[str, Any],
                                us: list[dict[str, Any]],
                                kr: list[dict[str, Any]]) -> AsyncIterator[str]:
    bucket = summary_bucket()
    if _summary_cache.get("bucket") == bucket and _summary_cache.get("text"):
        yield _sse("phase", {"phase": "cached"})
        yield _sse("final", {"text": _summary_cache["text"], "cached": True})
        return

    def remember(text: str) -> None:
        _summary_cache.update(bucket=bucket, text=text)

    async for frame in _converse_sse(_MARKET_SYSTEM, market_prompt(overview, us, kr),
                                     on_final=remember):
        yield frame


def article_stream(title: str, text: str | None, link: str | None) -> AsyncIterator[str]:
    """Article analysis SSE stream. Full text is optional (RSS gives
    title+link); the model is told when only the headline is available."""
    parts = [f"기사 제목: {title}"]
    if link:
        parts.append(f"링크: {link}")
    if text:
        parts.append(f"본문:\n{text}")
    else:
        parts.append("본문 없음 — 제목(과 링크)만으로 분석하라.")
    parts.append("위 기사를 분석하라.")
    return _converse_sse(_ARTICLE_SYSTEM, "\n".join(parts))

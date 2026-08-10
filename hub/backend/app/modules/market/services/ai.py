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
from typing import Any, AsyncIterator

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


def _stream_worker(detail: dict[str, Any], loop: asyncio.AbstractEventLoop,
                   queue: asyncio.Queue) -> None:
    """Blocking converse_stream iteration in a thread; pushes to async queue."""
    def put(item: tuple[str, Any]) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, item)

    try:
        resp = _get_client().converse_stream(
            modelId=config.BEDROCK_MODEL_ID,
            system=[{"text": _SYSTEM}],
            messages=[{"role": "user", "content": [{"text": _user_prompt(detail)}]}],
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


async def analyze_stream(detail: dict[str, Any]) -> AsyncIterator[str]:
    """SSE event stream: phase(fetching→analyzing) → delta* → final."""
    yield _sse("phase", {"phase": "fetching"})
    # detail is already fetched by the route (cached); transition immediately
    yield _sse("phase", {"phase": "analyzing"})

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    threading.Thread(target=_stream_worker, args=(detail, loop, queue),
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
            yield _sse("final", {"text": "".join(parts)})
            return

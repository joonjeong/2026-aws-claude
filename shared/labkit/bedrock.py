"""Bedrock Converse via direct REST (httpx, no SDK), with time-bucket caching.

Error contract (shared across the capstones' specs):
- token env var missing        → BedrockError(503) — panel/endpoint disables itself
- upstream non-200 / timeout / parse failure → BedrockError(502), status code only
  in the message; the upstream body goes to the log, never to callers.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from .cache import time_bucket

logger = logging.getLogger(__name__)

TOKEN_ENV = "AWS_BEARER_TOKEN_BEDROCK"
DEFAULT_MODEL = "global.anthropic.claude-sonnet-4-6"
DEFAULT_REGION = "ap-northeast-2"


class BedrockError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


async def converse(
    system: str,
    user_text: str,
    max_tokens: int,
    model: str = DEFAULT_MODEL,
    region: str = DEFAULT_REGION,
    timeout_s: float = 60.0,
) -> str:
    token = os.environ.get(TOKEN_ENV)
    if not token:
        raise BedrockError(503, f"{TOKEN_ENV} is not set")

    url = f"https://bedrock-runtime.{region}.amazonaws.com/model/{model}/converse"
    body: dict[str, Any] = {
        "system": [{"text": system}],
        "messages": [{"role": "user", "content": [{"text": user_text}]}],
        "inferenceConfig": {"maxTokens": max_tokens},
    }
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.post(
                url,
                json=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            )
    except httpx.HTTPError as exc:
        logger.error("bedrock request failed: %s", exc)
        raise BedrockError(502, "bedrock request failed") from exc

    if resp.status_code != 200:
        logger.error("bedrock upstream %s: %s", resp.status_code, resp.text[:2000])
        raise BedrockError(502, f"bedrock upstream status {resp.status_code}")

    try:
        data = resp.json()
        parts = data["output"]["message"]["content"]
        text = "".join(p.get("text", "") for p in parts)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        logger.error("bedrock response parse failed: %s", resp.text[:2000])
        raise BedrockError(502, "bedrock response parse failed") from exc
    if not text:
        raise BedrockError(502, "bedrock returned empty text")
    return text


class BucketCachedText:
    """Caches one generated text per time bucket (e.g. 600s → 10 minutes).

    generate() returns (text, cached, bucket). Multiple named slots are
    supported via `key` so one instance can serve e.g. now/daily modes.
    """

    def __init__(self, bucket_s: int) -> None:
        self.bucket_s = bucket_s
        self._cache: dict[str, tuple[int, str]] = {}

    async def generate(self, key: str = "default", **converse_kwargs: Any) -> tuple[str, bool, int]:
        bucket = time_bucket(self.bucket_s)
        entry = self._cache.get(key)
        if entry is not None and entry[0] == bucket:
            return entry[1], True, bucket
        text = await converse(**converse_kwargs)
        self._cache[key] = (bucket, text)
        return text, False, bucket

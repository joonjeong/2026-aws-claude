"""OpenSky OAuth2 client-credentials 토큰 — 만료 60초 전 갱신, 실패 시 익명 폴백."""
from __future__ import annotations

import logging
import time

import httpx

from . import config

logger = logging.getLogger(__name__)

_token: tuple[float, str] | None = None  # (expires_at, access_token)


async def get_token() -> str | None:
    """자격증명 미설정·발급 실패 → None (호출자는 익명으로 진행)."""
    global _token
    if not config.HAS_AUTH:
        return None
    now = time.time()
    if _token is not None and _token[0] > now + 60:
        return _token[1]
    try:
        async with httpx.AsyncClient(timeout=config.FETCH_TIMEOUT_S) as client:
            resp = await client.post(config.TOKEN_URL, data={
                "grant_type": "client_credentials",
                "client_id": config.CLIENT_ID,
                "client_secret": config.CLIENT_SECRET,
            })
            resp.raise_for_status()
            data = resp.json()
        _token = (now + float(data.get("expires_in", 1800)), data["access_token"])
        return _token[1]
    except Exception as exc:  # noqa: BLE001 — 토큰 실패가 수집을 막지 않는다
        logger.warning("opensky token fetch failed (anonymous fallback): %s", exc)
        return None

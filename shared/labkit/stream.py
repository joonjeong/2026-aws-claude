"""Persistent WebSocket collector — PollingCollector's streaming sibling.

Reconnects with exponential backoff (backoff_initial_s → backoff_max_s).
Per-message failures are isolated (logged, stream continues); connection
failures are recorded in `status` and retried. `connect` is injectable so
tests never open sockets.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


async def _default_connect(url: str) -> Any:
    import websockets

    return await websockets.connect(url)


class StreamCollector:
    def __init__(
        self,
        name: str,
        url: str,
        on_message: Callable[[dict], None],
        subscribe: Callable[[], dict] | None = None,
        backoff_initial_s: float = 1.0,
        backoff_max_s: float = 60.0,
        connect: Callable[[str], Awaitable[Any]] | None = None,
    ) -> None:
        self.name = name
        self.url = url
        self._on_message = on_message
        self._subscribe = subscribe
        self.backoff_initial_s = backoff_initial_s
        self.backoff_max_s = backoff_max_s
        self._connect = connect or _default_connect
        self._task: asyncio.Task | None = None
        self._ws: Any = None
        self.connected = False
        self.last_msg_at: float | None = None
        self.msg_count = 0
        self.reconnects = 0
        self.last_error: str | None = None

    @property
    def status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "connected": self.connected,
            "last_msg_at": self.last_msg_at,
            "msg_count": self.msg_count,
            "reconnects": self.reconnects,
            "last_error": self.last_error,
        }

    def resubscribe(self) -> None:
        """Re-send the subscription on the live socket (e.g. preset switch).
        No socket → the next (re)connect picks up the new subscribe() value."""
        ws = self._ws
        if ws is not None and self._subscribe is not None:
            asyncio.create_task(self._send_subscribe(ws))

    async def _send_subscribe(self, ws: Any) -> None:
        try:
            assert self._subscribe is not None
            await ws.send(json.dumps(self._subscribe()))
        except Exception as exc:  # 전송 실패 → 수신 루프가 끊김을 감지해 재접속
            logger.warning("[%s] subscribe send failed: %s", self.name, exc)

    async def _run_forever(self) -> None:
        backoff = self.backoff_initial_s
        while True:
            try:
                ws = await self._connect(self.url)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.reconnects += 1
                self.last_error = f"{type(exc).__name__}: {exc}"
                logger.warning("[%s] connect failed: %s", self.name, self.last_error)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self.backoff_max_s)
                continue

            self._ws = ws
            self.connected = True
            backoff = self.backoff_initial_s
            try:
                if self._subscribe is not None:
                    await self._send_subscribe(ws)
                async for raw in ws:
                    self.msg_count += 1
                    self.last_msg_at = time.time()
                    try:
                        self._on_message(json.loads(raw))
                    except Exception:  # 메시지 건별 격리
                        logger.warning("[%s] message handler failed", self.name,
                                       exc_info=True)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                logger.warning("[%s] stream dropped: %s", self.name, self.last_error)
            finally:
                self.connected = False
                self._ws = None
                try:
                    await ws.close()
                except Exception:  # noqa: BLE001 — 이미 죽은 소켓
                    pass
            self.reconnects += 1
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, self.backoff_max_s)

    def start(self) -> asyncio.Task:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(
                self._run_forever(), name=f"stream:{self.name}"
            )
        return self._task

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None
        self.connected = False
        self._ws = None

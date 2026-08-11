"""코어 타입 — 소스는 저장을 전혀 모르고 Record만 반환한다 (설계 §4).

Record.payload는 외부 응답 원본 그대로. 정규화는 각 소스 모듈의
normalize* 함수가 별도로 제공하며 SQLite 싱크에서만 쓰인다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable


@dataclass(frozen=True)
class Record:
    source: str
    kind: str
    payload: Any
    meta: dict = field(default_factory=dict)
    fetched_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class Job:
    name: str
    interval_s: float
    fetch: Callable[[], Awaitable[list[Record]]]


@runtime_checkable
class PollSource(Protocol):
    id: str

    def jobs(self) -> list[Job]: ...


@runtime_checkable
class StreamSource(Protocol):
    id: str
    url: str

    def subscribe_payload(self) -> dict | None: ...

    # labkit StreamCollector가 json.loads를 이미 수행 — dict를 받는다
    def parse(self, msg: dict) -> list[Record]: ...

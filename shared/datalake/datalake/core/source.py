"""코어 타입 — 클라이언트는 저장을 전혀 모르고 Record만 반환한다 (설계 §4).

Record.payload는 외부 응답 원본 그대로. 정규화는 각 소스 모듈의
normalize* 함수가 별도로 제공하며 SQLite 싱크에서만 쓰인다.
스케줄 메타(주기)는 두지 않는다 — 케이던스는 외부 오케스트레이터
(Temporal 예정)가 소유하고, 권장값은 README에 문서로만 남긴다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Record:
    source: str
    kind: str
    payload: Any
    meta: dict = field(default_factory=dict)
    fetched_at: float = field(default_factory=time.time)

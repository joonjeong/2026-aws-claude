"""소스 레지스트리.

각 소스 모듈은 `build() -> PollSource | StreamSource | None`을 노출한다.
None = 비활성 (키 부재·엑스트라 미설치) — 프로세스는 정상 기동한다.
"""

from __future__ import annotations

import importlib
import logging

log = logging.getLogger("datalake.sources")

# 구현된 소스만 나열 (태스크 진행에 따라 추가)
SOURCE_MODULES: list[str] = []


def build_sources(selected: list[str] | None = None) -> tuple[list, list]:
    """(poll_sources, stream_sources) 반환. 알 수 없는 소스명은 즉시 에러."""
    names = selected if selected is not None else list(SOURCE_MODULES)
    unknown = [n for n in names if n not in SOURCE_MODULES]
    if unknown:
        raise ValueError(f"알 수 없는 소스: {unknown} (사용 가능: {SOURCE_MODULES})")

    polls, streams = [], []
    for name in names:
        mod = importlib.import_module(f".{name}", __package__)
        built = mod.build()
        if built is None:
            log.info("소스 %s 비활성 (키 부재 또는 의존성 미설치)", name)
            continue
        if hasattr(built, "jobs"):
            polls.append(built)
        else:
            streams.append(built)
    return polls, streams

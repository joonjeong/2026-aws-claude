"""uv run datalake-flashpoint — GDELT 15분 export 1회 수집. 권장 스케줄: 900s.

같은 파일 재등장은 빈 배치 — 상태 파일(<ROOT>/_state/flashpoint_last_url)로
one-shot 실행 간에도 중복을 막는다. --force로 무시 가능.
"""

from __future__ import annotations


from .. import config
from ..sources import flashpoint
from . import _common

STATE_PATH = config.ROOT / "_state" / "flashpoint_last_url"


async def _run(args) -> int:
    sinks = _common.build_sinks()
    try:
        client = flashpoint.build(state_path=STATE_PATH)
        records = await client.fetch(force=args.force)
        _common.report("flashpoint", _common.emit(sinks, records))
    finally:
        _common.close_sinks(sinks)
    return _common.EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = _common.base_parser("datalake-flashpoint", __doc__)
    parser.add_argument("--force", action="store_true",
                        help="상태 파일 무시하고 최신 파일 재수집")
    args = parser.parse_args(argv)
    return _common.run_async(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())

"""uv run datalake-pykrx — KRX 시세 1회 수집 (kind: market_quotes_kr).

대상: market_symbols.toml. 권장 스케줄: 장중 45s / 장외 600s.
"""

from __future__ import annotations

import logging

from ..sources import pykrx
from . import _common

log = logging.getLogger("datalake.cli")


async def _run(args) -> int:
    root = _common.resolve_root(args)
    client = pykrx.build()
    sinks = _common.build_sinks(root)
    try:
        records = await client.fetch()
        _common.report("pykrx", _common.emit(sinks, records), root)
    finally:
        _common.close_sinks(sinks)
    return _common.EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = _common.base_parser("datalake-pykrx", __doc__).parse_args(argv)
    return _common.run_async(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())

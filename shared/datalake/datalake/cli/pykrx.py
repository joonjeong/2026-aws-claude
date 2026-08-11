"""uv run datalake-pykrx — KRX 시세 1회 수집 (kind: market_quotes_kr).

`--extra market` 필요. 권장 스케줄: 장중 45s / 장외 600s.
"""

from __future__ import annotations

import logging

from ..sources import pykrx
from . import _common

log = logging.getLogger("datalake.cli")


async def _run(args) -> int:
    client = pykrx.build()
    if client is None:
        log.error("pykrx 비활성: uv sync --extra market 필요")
        return _common.EXIT_DISABLED
    sinks = _common.build_sinks()
    try:
        records = await client.fetch()
        _common.report("pykrx", _common.emit(sinks, records))
    finally:
        _common.close_sinks(sinks)
    return _common.EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = _common.base_parser("datalake-pykrx", __doc__).parse_args(argv)
    return _common.run_async(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())

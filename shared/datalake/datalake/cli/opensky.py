"""uv run datalake-opensky — OpenSky 1회 수집 (kind: contrail_global/region_*).

adsblol과 같은 kind를 생산 — silver에서 제공자 중립 테이블로 수렴.
DATALAKE_OPENSKY_CLIENT_ID/SECRET 설정 시 인증, 없으면 익명 감속 모드.
주의: 데이터센터 IP 차단 실측 — 클라우드 배치는 datalake-adsblol 사용.
"""

from __future__ import annotations

from .. import config
from ..sources import opensky
from . import _common


async def _run(args) -> int:
    sinks = _common.build_sinks()
    client = opensky.build(
        state_path=config.ROOT / "_state" / "opensky_token.json")
    try:
        records = []
        if args.scope in ("global", "both"):
            records.extend(await client.fetch_global())
        if args.scope in ("regions", "both"):
            records.extend(await client.fetch_regions())
        _common.report("opensky", _common.emit(sinks, records))
    finally:
        _common.close_sinks(sinks)
    return _common.EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = _common.base_parser("datalake-opensky", __doc__)
    parser.add_argument("--scope", choices=("global", "regions", "both"),
                        default="both", help="수집 범위 (기본: both)")
    args = parser.parse_args(argv)
    return _common.run_async(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())

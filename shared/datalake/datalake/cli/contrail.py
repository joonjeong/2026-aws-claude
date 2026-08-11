"""uv run datalake-contrail — 항공 트래픽 1회 수집 (adsb.lol 기본 / OpenSky).

권장 스케줄: --scope regions 60s, --scope global 600s (hub 기본값).
프리셋 4개는 내부에서 순차 1.1s 간격으로 조회한다 (상류 빈도 제한 예의).
OpenSky는 DATALAKE_OPENSKY_CLIENT_ID/SECRET 설정 시 인증, 없으면 익명 감속.
"""

from __future__ import annotations


from .. import config
from ..sources import contrail
from . import _common


async def _run(args) -> int:
    sinks = _common.build_sinks()
    client = contrail.build(
        provider=args.provider,
        state_path=config.ROOT / "_state" / "opensky_token.json",
    )
    try:
        records = []
        if args.scope in ("global", "both"):
            records.extend(await client.fetch_global())
        if args.scope in ("regions", "both"):
            records.extend(await client.fetch_regions())
        _common.report("contrail", _common.emit(sinks, records))
    finally:
        _common.close_sinks(sinks)
    return _common.EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = _common.base_parser("datalake-contrail", __doc__)
    parser.add_argument("--scope", choices=("global", "regions", "both"),
                        default="both", help="수집 범위 (기본: both)")
    parser.add_argument("--provider", choices=sorted(contrail.PROVIDERS),
                        default=None,
                        help="상류 제공자 (기본: env DATALAKE_CONTRAIL_PROVIDER=adsblol)")
    args = parser.parse_args(argv)
    return _common.run_async(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())

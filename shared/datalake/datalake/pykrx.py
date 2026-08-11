"""uv run datalake-pykrx — KRX 시세 수집 (자기완결). 권장: 장중 45s / 장외 600s.

수집 대상은 market_symbols.toml이 관리. pykrx의 시장 전체 스냅샷은 KRX
포털 로그인이 필요해 종목당 조회 경로 사용 (세마포어 8 — 라이브러리가
찍는 "KRX 로그인 실패" 경고는 무해).
파이프라인: 종목별 fetch(격리) → 행 변환(순수) →
landing/pykrx/market_quotes_kr + bronze/market_quotes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tomllib
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Optional

import typer

log = logging.getLogger("datalake.pykrx")

SOURCE = "pykrx"
KIND = "market_quotes_kr"
_CONCURRENCY = 8
DEFAULT_ROOT = Path(os.environ.get(
    "DATALAKE_ROOT", str(Path(__file__).resolve().parent.parent / "data")))


def load_symbols() -> dict:
    override = os.environ.get("DATALAKE_MARKET_SYMBOLS")
    path = (Path(override) if override
            else Path(__file__).with_name("market_symbols.toml"))
    return tomllib.loads(path.read_text(encoding="utf-8"))


def active_kr() -> list[tuple[str, str]]:
    n = int(os.environ.get("DATALAKE_MARKET_ACTIVE_KR", "20"))
    return [tuple(x) for x in load_symbols()["kr"]["symbols"][:n]]


# ── 시세 행 (hub market services/kr.py와 동일 의미) ──────────────────
def _quote_row(code: str, name: str) -> dict:
    from pykrx import stock

    end = date.today()
    start = end - timedelta(days=14)  # 거래일 2일 이상 확보
    df = stock.get_market_ohlcv_by_date(start.strftime("%Y%m%d"),
                                        end.strftime("%Y%m%d"), code)
    if df is None or df.empty:
        raise ValueError("empty ohlcv")
    close = float(df["종가"].iloc[-1])
    prev = float(df["종가"].iloc[-2]) if len(df) >= 2 else close
    return {"symbol": code, "name": name, "price": close,
            "change": round(close - prev, 2),
            "change_pct": round((close - prev) / prev * 100, 2) if prev else 0.0,
            "volume": int(df["거래량"].iloc[-1])}


async def fetch_quotes() -> list[dict]:
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def one(code: str, name: str) -> dict | None:
        async with sem:
            try:  # 심볼 단위 격리
                return await asyncio.to_thread(_quote_row, code, name)
            except Exception as exc:  # noqa: BLE001
                log.warning("KR symbol %s skipped: %s", code, exc)
                return None

    results = await asyncio.gather(*(one(c, n) for c, n in active_kr()))
    rows = [r for r in results if r]
    if not rows:
        raise RuntimeError("all KR symbols failed")
    return rows


def to_quote_row(q: dict, ts: float) -> dict:
    return {"source": SOURCE, "ts": ts, "kind": "quote_kr", "market": "KR",
            **{k: q.get(k) for k in ("symbol", "name", "price", "change",
                                     "change_pct", "volume")}}


# ── 랜딩 ────────────────────────────────────────────────────────────
def _jsonl(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _append(path: Path, lines: list[str]) -> None:
    if not lines:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _part(root: Path, zone: str, *dirs: str, ts: float) -> Path:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return root.joinpath(zone, *dirs, f"dt={dt:%Y-%m-%d}", f"part-{dt:%H}.jsonl")


def land(root: Path, ts: float, payload: list[dict], meta: dict) -> int:
    envelope = {
        "fetched_at": datetime.fromtimestamp(ts, tz=timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": SOURCE, "kind": KIND, "meta": meta, "payload": payload,
    }
    rows = [to_quote_row(q, ts) for q in payload]
    _append(_part(root, "landing", SOURCE, KIND, ts=ts), [_jsonl(envelope)])
    _append(_part(root, "bronze", "market_quotes", f"source={SOURCE}", ts=ts),
            [_jsonl(r) for r in rows])
    return len(rows)


# ── 수집 ─────────────────────────────────────────────────────────────
async def collect(root: Path, fetcher=None) -> int:
    started = time.monotonic()
    payload = await (fetcher() if fetcher is not None else fetch_quotes())
    meta = {"elapsed_ms": int((time.monotonic() - started) * 1000)}
    n = land(root, time.time(), payload, meta)
    log.info("[%s] bronze %d행 → %s", SOURCE, n, root)
    return 0


def cli(output: Annotated[Optional[Path], typer.Option(
        help="레이크 루트 (기본: env DATALAKE_ROOT)")] = None) -> None:
    """KRX 시세 1회 수집 → landing + bronze."""
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        asyncio.run(collect(output or DEFAULT_ROOT))
    except Exception as exc:
        log.error("실패: %s: %s", type(exc).__name__, exc)
        raise typer.Exit(1)


def main() -> None:
    typer.run(cli)


if __name__ == "__main__":
    main()

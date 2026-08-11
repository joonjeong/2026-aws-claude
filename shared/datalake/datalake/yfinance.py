"""uv run datalake-yfinance — Yahoo Finance 시세 수집 (자기완결).

수집 대상(심볼·지수·지표)은 market_symbols.toml이 관리
(env DATALAKE_MARKET_SYMBOLS로 교체). 권장: 장중 45s / 장외 600s
(비공식 라이브러리 호출량 배려 — 케이던스는 외부 스케줄러 소유).
파이프라인: yfinance bulk download → 행 변환(순수 map/filter) →
landing/yfinance/market_* + bronze/market_quotes (평탄화).
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import tomllib
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Optional

import typer

log = logging.getLogger("datalake.yfinance")

SOURCE = "yfinance"
KINDS = ("market_overview", "market_quotes_us")
DEFAULT_ROOT = Path(os.environ.get(
    "DATALAKE_ROOT", str(Path(__file__).resolve().parent.parent / "data")))


def load_symbols() -> dict:
    override = os.environ.get("DATALAKE_MARKET_SYMBOLS")
    path = (Path(override) if override
            else Path(__file__).with_name("market_symbols.toml"))
    return tomllib.loads(path.read_text(encoding="utf-8"))


def active_us() -> list[tuple[str, str]]:
    n = int(os.environ.get("DATALAKE_MARKET_ACTIVE_US", "20"))
    return [tuple(x) for x in load_symbols()["us"]["symbols"][:n]]


def indices() -> list[tuple[str, str, str]]:
    return [tuple(x) for x in load_symbols()["indices"]["items"]]


def indicators() -> list[tuple[str, str]]:
    return [tuple(x) for x in load_symbols()["indicators"]["items"]]


# ── 시세 행 (hub market services/us.py와 동일 의미) ──────────────────
def _last_two_closes(df) -> tuple[float, float, int]:
    closes = df["Close"].dropna()
    if closes.empty:
        raise ValueError("no close data")
    last = float(closes.iloc[-1])
    prev = float(closes.iloc[-2]) if len(closes) >= 2 else last
    vols = df["Volume"].dropna() if "Volume" in df else None
    vol = 0
    if vols is not None and not vols.empty:
        v = vols.iloc[-1]
        vol = 0 if (isinstance(v, float) and math.isnan(v)) else int(v)
    return last, prev, vol


def _quote_rows(tickers: list[tuple[str, str]]) -> list[dict]:
    import yfinance as yf

    data = yf.download(tickers=" ".join(t for t, _ in tickers),
                       period="5d", interval="1d", group_by="ticker",
                       threads=True, progress=False, auto_adjust=False)

    def row(symbol: str, name: str) -> dict | None:
        try:  # 심볼 단위 격리
            df = (data[symbol]
                  if symbol in getattr(data.columns, "levels", [[]])[0] else data)
            last, prev, vol = _last_two_closes(df)
            return {"symbol": symbol, "name": name,
                    "price": round(last, 2), "change": round(last - prev, 2),
                    "change_pct": round((last - prev) / prev * 100, 2) if prev else 0.0,
                    "volume": vol}
        except Exception as exc:  # noqa: BLE001
            log.warning("US symbol %s skipped: %s", symbol, exc)
            return None

    return [r for r in (row(s, n) for s, n in tickers) if r]


def fetch_overview() -> dict:
    idx = indices()
    market_of = {t: m for t, _, m in idx}
    rows = _quote_rows([(t, n) for t, n, _ in idx])
    return {"indices": [{**r, "market": market_of.get(r["symbol"], "US")}
                        for r in rows],
            "indicators": _quote_rows(indicators())}


def fetch_quotes_us() -> list[dict]:
    return _quote_rows(active_us())


# ── bronze 평탄화 (market_quotes 행) ─────────────────────────────────
def to_quote_row(q: dict, kind: str, market: str | None, ts: float) -> dict:
    row = {"ts": ts, "kind": kind, "market": market,
           **{k: q.get(k) for k in ("symbol", "name", "price", "change",
                                    "change_pct", "volume")}}
    return {k: v for k, v in row.items() if v is not None}  # 값 없는 키 생략


def flatten(kind: str, payload, ts: float) -> list[dict]:
    if kind == "market_overview":
        return ([to_quote_row(q, "index", q.get("market"), ts)
                 for q in payload.get("indices") or []]
                + [to_quote_row(q, "indicator", None, ts)
                   for q in payload.get("indicators") or []])
    return [to_quote_row(q, "quote_us", "US", ts) for q in payload or []]


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


def land(root: Path, kind: str, ts: float, payload, meta: dict,
         keep_landing: bool = False) -> int:
    rows = flatten(kind, payload, ts)
    if keep_landing:  # 원본 봉투 보존은 옵트인 (--landing)
        envelope = {
            "fetched_at": datetime.fromtimestamp(ts, tz=timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": SOURCE, "kind": kind, "meta": meta, "payload": payload,
        }
        _append(_part(root, "landing", SOURCE, kind, ts=ts), [_jsonl(envelope)])
    _append(_part(root, "bronze", "market_quotes", f"source={SOURCE}", ts=ts),
            [_jsonl(r) for r in rows])
    return len(rows)


# ── 수집 ─────────────────────────────────────────────────────────────
async def collect(root: Path, kinds: list[str] | None = None,
                  keep_landing: bool = False,
                  fetchers: dict | None = None) -> int:
    fetchers = fetchers if fetchers is not None else {
        "market_overview": fetch_overview,
        "market_quotes_us": fetch_quotes_us,
    }
    total = 0
    for kind in (kinds or list(fetchers)):
        fetch = fetchers.get(kind)
        if fetch is None:
            raise ValueError(f"알 수 없는 kind: {kind} ({list(fetchers)})")
        started = time.monotonic()
        try:
            payload = await asyncio.to_thread(fetch)
        except Exception as exc:  # kind 단위 격리
            log.warning("%s fetch failed: %s: %s", kind, type(exc).__name__, exc)
            continue
        meta = {"elapsed_ms": int((time.monotonic() - started) * 1000)}
        total += land(root, kind, time.time(), payload, meta, keep_landing)
    log.info("[%s] bronze %d행 → %s", SOURCE, total, root)
    return 0


def cli(
    output: Annotated[Optional[Path], typer.Option(
        help="레이크 루트 (기본: env DATALAKE_ROOT)")] = None,
    kinds: Annotated[Optional[str], typer.Option(
        help="쉼표 구분 선택 (기본 전체: market_overview,market_quotes_us)")] = None,
    landing: Annotated[bool, typer.Option(
        "--landing", help="원본 봉투를 landing 존에도 보존")] = False,
) -> None:
    """Yahoo Finance 시세 1회 수집 → landing + bronze."""
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        asyncio.run(collect(output or DEFAULT_ROOT,
                            kinds.split(",") if kinds else None, landing))
    except Exception as exc:
        log.error("실패: %s: %s", type(exc).__name__, exc)
        raise typer.Exit(1)


def main() -> None:
    typer.run(cli)


if __name__ == "__main__":
    main()

"""uv run datalake-gdelt — GDELT v2 15분 export 수집 (자기완결). 권장 900s.

같은 파일 재등장은 빈 배치 — 상태 파일(_state/gdelt_last_url)로 one-shot
실행 간에도 중복을 막는다 (--force로 무시). 보안 가드 hub와 동일:
허용 프리픽스 밖 URL 거부(SSRF), follow_redirects=False, zip 폭탄 상한.
파이프라인: lastupdate.txt → zip → CSV 전문을 landing에 보존 →
CAMEO 루트 14~20 필터(순수 map/filter) → bronze/flashpoint_events.
"""

from __future__ import annotations

import argparse
import asyncio
import calendar
import io
import json
import logging
import os
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import httpx

log = logging.getLogger("datalake.gdelt")

SOURCE = "gdelt"
LASTUPDATE_URL = os.environ.get(
    "DATALAKE_GDELT_URL", "http://data.gdeltproject.org/gdeltv2/lastupdate.txt")
TIMEOUT_S = 30.0
DEFAULT_ROOT = Path(os.environ.get(
    "DATALAKE_ROOT", str(Path(__file__).resolve().parent.parent / "data")))

# lastupdate.txt와 같은 디렉터리만 허용 — 응답 오염 시 SSRF 방지 (hub 동일)
_ALLOWED_PREFIX = LASTUPDATE_URL.rsplit("/", 1)[0] + "/"
MAX_ZIP_BYTES = 20 * 1024 * 1024   # 실측 ~65KB — 여유 300배
MAX_CSV_BYTES = 200 * 1024 * 1024  # 압축해제 상한 (zip 폭탄 방지)

# CAMEO 루트 14 시위 ~ 20 대량폭력 (bronze 필터 — landing은 전문 보존)
ROOTS = {r.strip() for r in os.environ.get(
    "DATALAKE_GDELT_ROOTS", "14,15,16,17,18,19,20").split(",") if r.strip()}

# GDELT 2.0 event table 컬럼 인덱스 (hub와 동일 계약)
_ID, _SQLDATE, _ACTOR1, _ACTOR2 = 0, 1, 6, 16
_CODE, _ROOT, _QUAD, _GOLDSTEIN = 26, 28, 29, 30
_MENTIONS, _ARTICLES, _TONE = 31, 33, 34
_COUNTRY, _LAT, _LON, _DATEADDED, _URL = 53, 56, 57, 59, 60


def pick_export_url(lastupdate_txt: str) -> str:
    """lastupdate.txt 3줄 중 export URL — 허용 프리픽스 검증."""
    urls = (line.split()[-1] for line in lastupdate_txt.splitlines() if line.split())
    for url in urls:
        if url.endswith(".export.CSV.zip"):
            if not url.startswith(_ALLOWED_PREFIX):
                raise ValueError(f"export url outside allowed prefix: {url}")
            return url
    raise ValueError("no export.CSV.zip in lastupdate.txt")


def unzip_text(blob: bytes) -> str:
    zf = zipfile.ZipFile(io.BytesIO(blob))
    info = zf.infolist()[0]
    if info.file_size > MAX_CSV_BYTES:
        raise ValueError(f"csv too large: {info.file_size} bytes")
    return zf.read(info).decode("utf8", "ignore")


# ── 순수 파싱 (hub flashpoint normalize와 동일 의미) ─────────────────
def _num(raw, cast):
    try:
        return cast(raw)
    except (TypeError, ValueError):
        return None


def _text(raw) -> str | None:
    s = raw.strip()
    return s or None


def _url_or_none(raw) -> str | None:
    s = raw.strip()
    return s if s.startswith(("http://", "https://")) else None  # href XSS 차단


def _ts(dateadded: str) -> float:
    try:
        return float(calendar.timegm(time.strptime(dateadded, "%Y%m%d%H%M%S")))
    except ValueError:
        return time.time()


def to_event(line: str) -> dict | None:
    """TSV 행 → flashpoint_events 행. 필터 밖·비정상은 None."""
    try:
        c = line.split("\t")
        if len(c) < 61 or c[_ROOT] not in ROOTS or not c[_LAT] or not c[_LON]:
            return None
        event_id = _num(c[_ID], int)
        if event_id is None:
            return None
        return {
            "event_id": event_id, "ts": _ts(c[_DATEADDED]),
            "event_day": c[_SQLDATE] or None, "code": c[_CODE] or None,
            "root": c[_ROOT], "quad": _num(c[_QUAD], int),
            "goldstein": _num(c[_GOLDSTEIN], float),
            "mentions": _num(c[_MENTIONS], int),
            "articles": _num(c[_ARTICLES], int), "tone": _num(c[_TONE], float),
            "actor1": _text(c[_ACTOR1]), "actor2": _text(c[_ACTOR2]),
            "lat": float(c[_LAT]), "lon": float(c[_LON]),
            "country": _text(c[_COUNTRY]), "source_url": _url_or_none(c[_URL]),
        }
    except Exception:  # 행 단위 격리
        log.warning("skipping malformed gdelt row", exc_info=True)
        return None


def parse(csv_text: str) -> list[dict]:
    return [e for e in map(to_event, csv_text.splitlines()) if e]


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


def land(root: Path, ts: float, csv_text: str, meta: dict) -> int:
    envelope = {
        "fetched_at": datetime.fromtimestamp(ts, tz=timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": SOURCE, "kind": "flashpoint", "meta": meta,
        "payload": csv_text,  # CAMEO 필터 전 전문 보존
    }
    rows = parse(csv_text)
    _append(_part(root, "landing", SOURCE, "flashpoint", ts=ts), [_jsonl(envelope)])
    _append(_part(root, "bronze", "flashpoint_events", ts=ts),
            [_jsonl(r) for r in rows])
    return len(rows)


# ── 수집 (파일 단위 중복은 상태 파일로 스킵) ─────────────────────────
async def collect(root: Path, force: bool = False,
                  transport: httpx.AsyncBaseTransport | None = None) -> int:
    state_path = root / "_state" / "gdelt_last_url"
    started = time.monotonic()
    # follow_redirects=False: 프리픽스 검증 우회 차단 (hub와 동일 방어선)
    async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=False,
                                 transport=transport) as client:
        resp = await client.get(LASTUPDATE_URL)
        resp.raise_for_status()
        url = pick_export_url(resp.text)
        last = (state_path.read_text(encoding="utf-8").strip()
                if state_path.exists() else None)
        if not force and url == last:
            log.info("[%s] 새 15분 배치 아직 없음: %s", SOURCE, url)
            return 0
        blob = (await client.get(url)).raise_for_status().content
        if len(blob) > MAX_ZIP_BYTES:
            raise ValueError(f"zip too large: {len(blob)} bytes")
    csv_text = unzip_text(blob)
    ts = time.time()
    meta = {"url": url, "status": 200, "lines": len(csv_text.splitlines()),
            "elapsed_ms": int((time.monotonic() - started) * 1000)}
    n = land(root, ts, csv_text, meta)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(url, encoding="utf-8")  # 성공 후에만 갱신
    log.info("[%s] 봉투 1개 · 이벤트 %d행 → %s", SOURCE, n, root)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="datalake-gdelt", description=__doc__)
    parser.add_argument("--output", default=None, metavar="ROOT",
                        help="레이크 루트 (기본: env DATALAKE_ROOT)")
    parser.add_argument("--force", action="store_true",
                        help="상태 파일 무시하고 최신 파일 재수집")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        return asyncio.run(collect(
            Path(args.output) if args.output else DEFAULT_ROOT, args.force))
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        log.error("실패: %s: %s", type(exc).__name__, exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""flashpoint — GDELT v2 15분 export (분쟁·불안 이벤트). hub flashpoint와 동일 주기.

이식 원본: hub/backend/app/modules/flashpoint/{config,collector,normalize}.py. import 금지.

- 무료·무키. lastupdate.txt → 최신 export.CSV.zip 다운로드 (900s 폴)
- 레이크 payload는 **필터 전 CSV 전문** — hub는 CAMEO 루트 14~20만 남기고
  버리지만 레이크는 원문 보존 (SQLite 싱크에서만 hub 동형 필터 적용)
- 보안 가드 hub와 동일: 허용 프리픽스 밖 URL 거부(SSRF), follow_redirects=False,
  zip/해제 크기 상한 (zip 폭탄)
- 같은 파일 URL 재등장(15분 미도래)은 빈 배치 — 파일 단위 중복 방지
"""

from __future__ import annotations

import calendar
import io
import logging
import time
import zipfile

import httpx

from labkit.config import env_float, env_str

from ..core.source import Job, Record

log = logging.getLogger("datalake.flashpoint")

LASTUPDATE_URL = env_str(
    "DATALAKE_FLASHPOINT_URL",
    "http://data.gdeltproject.org/gdeltv2/lastupdate.txt",
)
INTERVAL_S = env_float("DATALAKE_FLASHPOINT_INTERVAL_S", 900.0)  # hub FLASHPOINT_POLL_S
TIMEOUT_S = env_float("DATALAKE_FLASHPOINT_TIMEOUT_S", 30.0)

# lastupdate.txt와 같은 디렉터리의 파일만 허용 — 평문 HTTP 응답 오염 시
# 임의 호스트로 GET이 나가는 것(SSRF) 방지 (hub와 동일)
_ALLOWED_PREFIX = LASTUPDATE_URL.rsplit("/", 1)[0] + "/"
MAX_ZIP_BYTES = 20 * 1024 * 1024   # 실측 ~65KB — 여유 300배
MAX_CSV_BYTES = 200 * 1024 * 1024  # 압축해제 상한 (zip 폭탄 방지)

# CAMEO 루트코드 필터 — 14 시위 ~ 20 대량폭력 (SQLite 싱크용, hub와 동일)
ROOTS = {
    r.strip()
    for r in env_str("DATALAKE_FLASHPOINT_ROOTS", "14,15,16,17,18,19,20").split(",")
    if r.strip()
}

# 사용 컬럼 인덱스 (GDELT 2.0 event table — hub normalize.py 계약과 동일)
_ID, _SQLDATE, _ACTOR1, _ACTOR2 = 0, 1, 6, 16
_CODE, _ROOT, _QUAD, _GOLDSTEIN = 26, 28, 29, 30
_MENTIONS, _ARTICLES, _TONE = 31, 33, 34
_COUNTRY, _LAT, _LON, _DATEADDED, _URL = 53, 56, 57, 59, 60


def pick_export_url(lastupdate_txt: str) -> str:
    """lastupdate.txt 3줄(export/mentions/gkg) 중 export URL 선택."""
    for line in lastupdate_txt.splitlines():
        parts = line.split()
        if parts and parts[-1].endswith(".export.CSV.zip"):
            url = parts[-1]
            if not url.startswith(_ALLOWED_PREFIX):
                raise ValueError(f"export url outside allowed prefix: {url}")
            return url
    raise ValueError("no export.CSV.zip in lastupdate.txt")


def _unzip_text(blob: bytes, max_csv_bytes: int = MAX_CSV_BYTES) -> str:
    zf = zipfile.ZipFile(io.BytesIO(blob))
    info = zf.infolist()[0]
    if info.file_size > max_csv_bytes:
        raise ValueError(f"csv too large: {info.file_size} bytes")
    return zf.read(info).decode("utf8", "ignore")


def _clean(raw: str) -> str | None:
    s = raw.strip()
    return s or None


def _clean_url(raw: str) -> str | None:
    """href로 렌더링될 수 있는 값 — http(s) 외 스킴(javascript: 등) 차단."""
    s = raw.strip()
    return s if s.startswith(("http://", "https://")) else None


def _num(raw: str, cast) -> float | int | None:
    try:
        return cast(raw)
    except (TypeError, ValueError):
        return None


def _ts(dateadded: str) -> float:
    """DATEADDED(YYYYMMDDHHMMSS, UTC) → epoch. 실패 시 현재 시각."""
    try:
        st = time.strptime(dateadded, "%Y%m%d%H%M%S")
        return float(calendar.timegm(st))
    except ValueError:
        return time.time()


def normalize(lines, roots: set[str] | None = None) -> list[dict]:
    """hub normalize_export()와 동일 — 루트 필터, 좌표 필수, 행 단위 격리."""
    roots = ROOTS if roots is None else roots
    if isinstance(lines, str):
        lines = lines.splitlines()
    out: list[dict] = []
    for line in lines:
        try:
            c = line.split("\t")
            if len(c) < 61 or c[_ROOT] not in roots:
                continue
            if not c[_LAT] or not c[_LON]:
                continue
            event_id = _num(c[_ID], int)
            if event_id is None:
                continue
            out.append({
                "event_id": event_id,
                "ts": _ts(c[_DATEADDED]),
                "event_day": c[_SQLDATE] or None,
                "code": c[_CODE] or None,
                "root": c[_ROOT],
                "quad": _num(c[_QUAD], int),
                "goldstein": _num(c[_GOLDSTEIN], float),
                "mentions": _num(c[_MENTIONS], int),
                "articles": _num(c[_ARTICLES], int),
                "tone": _num(c[_TONE], float),
                "actor1": _clean(c[_ACTOR1]),
                "actor2": _clean(c[_ACTOR2]),
                "lat": float(c[_LAT]),
                "lon": float(c[_LON]),
                "country": _clean(c[_COUNTRY]),
                "source_url": _clean_url(c[_URL]),
            })
        except Exception:  # 한 행의 비정상이 배치를 죽이지 않음
            log.warning("skipping malformed gdelt row", exc_info=True)
    return out


class FlashpointSource:
    id = "flashpoint"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport
        self._last_url: str | None = None

    async def _fetch(self) -> list[Record]:
        started = time.monotonic()
        # follow_redirects=False: 프리픽스 검증을 통과한 URL이 리다이렉트로
        # 임의 호스트에 닿는 우회 차단 (hub와 동일한 방어선)
        async with httpx.AsyncClient(
            timeout=TIMEOUT_S, follow_redirects=False, transport=self._transport
        ) as client:
            resp = await client.get(LASTUPDATE_URL)
            resp.raise_for_status()
            url = pick_export_url(resp.text)
            if url == self._last_url:
                return []  # 새 15분 배치 아직 없음
            blob = (await client.get(url)).raise_for_status().content
            if len(blob) > MAX_ZIP_BYTES:
                raise ValueError(f"zip too large: {len(blob)} bytes")
        csv_text = _unzip_text(blob)
        self._last_url = url  # 다운로드·파싱 성공 후에만 갱신 (실패 시 재시도)
        return [
            Record(
                source=self.id,
                kind="export",
                payload=csv_text,
                meta={
                    "url": url,
                    "status": 200,
                    "lines": len(csv_text.splitlines()),
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                },
            )
        ]

    def jobs(self) -> list[Job]:
        return [Job("flashpoint-gdelt", INTERVAL_S, self._fetch)]


def build() -> FlashpointSource:
    return FlashpointSource()

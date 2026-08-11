"""GDELT 폴러 — lastupdate.txt → 최신 export.CSV.zip → 정규화 → DB 배치 기록.

같은 파일 URL 재등장(15분 미도래)은 빈 배치로 처리. 재시작 후 같은 파일
재처리는 event_id PK(INSERT OR IGNORE) 멱등으로 흡수.
"""
from __future__ import annotations

import io
import logging
import zipfile

import httpx
from labkit import PollingCollector

from ...archive import archive_insert
from . import config, schema
from .normalize import normalize_export

logger = logging.getLogger(__name__)

_last_url: str | None = None
# lastupdate.txt와 같은 디렉터리의 파일만 허용 — 평문 HTTP 응답 오염 시
# 임의 호스트로 GET이 나가는 것(SSRF) 방지
_ALLOWED_PREFIX = config.LASTUPDATE_URL.rsplit("/", 1)[0] + "/"
MAX_ZIP_BYTES = 20 * 1024 * 1024      # 실측 ~65KB — 여유 300배
MAX_CSV_BYTES = 200 * 1024 * 1024     # 압축해제 상한 (zip 폭탄 방지)
# dict인 이유: __init__이 패키지 속성 `collector`를 인스턴스로 재바인딩하므로
# 모듈 경유 속성 접근이 깨진다 — 객체 참조를 직접 임포트해 제자리 갱신.
ingest_stats = {"last_batch": 0, "total_rows": 0}


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


def _unzip_lines(blob: bytes, max_csv_bytes: int = MAX_CSV_BYTES) -> list[str]:
    zf = zipfile.ZipFile(io.BytesIO(blob))
    info = zf.infolist()[0]
    if info.file_size > max_csv_bytes:
        raise ValueError(f"csv too large: {info.file_size} bytes")
    return zf.read(info).decode("utf8", "ignore").splitlines()


async def fetch_latest() -> list[dict]:
    global _last_url
    async with httpx.AsyncClient(timeout=config.FETCH_TIMEOUT_S) as client:
        resp = await client.get(config.LASTUPDATE_URL)
        resp.raise_for_status()
        url = pick_export_url(resp.text)
        if url == _last_url:
            return []  # 새 15분 배치 아직 없음
        blob = (await client.get(url)).raise_for_status().content
        if len(blob) > MAX_ZIP_BYTES:
            raise ValueError(f"zip too large: {len(blob)} bytes")
    events = normalize_export(_unzip_lines(blob), roots=config.ROOTS)
    _last_url = url  # 다운로드·파싱 성공 후에만 갱신 — 실패 시 다음 사이클 재시도
    return events


def _on_events(events: list[dict]) -> None:
    rows = [(
        e["event_id"], e["ts"], e["event_day"], e["code"], e["root"], e["quad"],
        e["goldstein"], e["mentions"], e["articles"], e["tone"],
        e["actor1"], e["actor2"], e["lat"], e["lon"], e["country"],
        e["source_url"],
    ) for e in events]
    archive_insert(schema.INSERT_EVENT, rows)  # best-effort — 실패는 로그만
    ingest_stats["last_batch"] = len(rows)
    ingest_stats["total_rows"] += len(rows)


collector = PollingCollector(
    name="flashpoint-gdelt",
    interval_s=config.POLL_S,
    fetch=fetch_latest,
    on_result=_on_events,
)

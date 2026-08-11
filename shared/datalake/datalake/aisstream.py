"""uv run datalake-aisstream — AISStream 해상 트래픽 스트림 수집 (자기완결).

DATALAKE_AIS_KEY 필요 (없으면 종료 코드 2, hub 키 공유 금지 — 동시 연결
제한). --duration N 초 구독 후 종료 (0 = Ctrl-C까지). 재접속은 지수 백오프.
파이프라인: WebSocket 구독 → 메시지 버퍼(플러시 10s) → parse(순수) →
landing/aisstream/wake + bronze/wake_vessels·wake_positions.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Annotated, Optional

import typer
from pydantic import BaseModel, BeforeValidator

log = logging.getLogger("datalake.aisstream")

SOURCE = "aisstream"
STREAM_URL = os.environ.get("DATALAKE_AIS_URL", "wss://stream.aisstream.io/v0/stream")
FLUSH_S = float(os.environ.get("DATALAKE_FLUSH_S", "10"))
DEFAULT_PRESET = os.environ.get("DATALAKE_AISSTREAM_PRESET", "kr")
DEFAULT_ROOT = Path(os.environ.get(
    "DATALAKE_ROOT", str(Path(__file__).resolve().parent.parent / "data")))

# bbox = (lat_min, lon_min, lat_max, lon_max) — hub wake 프리셋과 동일
PRESETS: dict[str, tuple] = {
    "kr": (30.0, 120.0, 45.0, 135.0),
    "taiwan": (20.0, 115.0, 28.0, 125.0),
    "sea": (-10.0, 95.0, 15.0, 120.0),
}


def subscribe_payload(api_key: str, preset: str) -> dict:
    lat_min, lon_min, lat_max, lon_max = PRESETS[preset]
    return {
        "APIKey": api_key,
        "BoundingBoxes": [[[lat_min, lon_min], [lat_max, lon_max]]],
        "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
    }


# ── 순수 파싱 (hub wake normalize와 동일 의미) ───────────────────────
def ship_type_label(code) -> str:
    """AIS ship type → 대분류 (ITU-R M.1371)."""
    try:
        code = int(code)
    except (TypeError, ValueError):
        return "기타"
    return ("어선" if code == 30 else
            "여객" if 60 <= code <= 69 else
            "화물" if 70 <= code <= 79 else
            "탱커" if 80 <= code <= 89 else "기타")


# 센티널·정리는 pydantic 필드 선언으로 (BeforeValidator 이디엄)
def _sentinel(*bad):
    """AIS '값 없음' 센티널 → None."""
    return BeforeValidator(lambda v: None if v in bad else v)


OptName = Annotated[Optional[str],
                    BeforeValidator(lambda v: (str(v).strip() or None) if v else None)]


class WakePosition(BaseModel):
    mmsi: str
    ts: float
    lon: float
    lat: float
    sog_kn: Annotated[Optional[float], _sentinel(None, 102.3)] = None
    cog_deg: Annotated[Optional[float], _sentinel(None, 360.0)] = None
    heading_deg: Annotated[Optional[float], _sentinel(None, 511)] = None


class WakeVessel(BaseModel):
    mmsi: str
    name: OptName = None
    ship_type: Optional[str] = None
    callsign: OptName = None
    first_seen: float
    last_seen: float


def to_vessel_and_position(msg: dict, now: float) -> dict[str, list[dict]]:
    """AIS 메시지 → bronze 행들 (센티널 처리는 모델이 담당)."""
    meta = msg.get("MetaData") or {}
    mmsi = meta.get("MMSI")
    if mmsi is None:
        return {}
    mtype = msg.get("MessageType")
    if mtype == "PositionReport":
        body = ((msg.get("Message") or {}).get("PositionReport")) or {}
        if body.get("Latitude") is None or body.get("Longitude") is None:
            return {}
        return {
            "wake_vessels": [WakeVessel(
                mmsi=str(mmsi), name=meta.get("ShipName"),
                first_seen=now, last_seen=now).model_dump(exclude_none=True)],
            "wake_positions": [WakePosition(
                mmsi=str(mmsi), ts=now, lon=body["Longitude"], lat=body["Latitude"],
                sog_kn=body.get("Sog"), cog_deg=body.get("Cog"),
                heading_deg=body.get("TrueHeading")).model_dump(exclude_none=True)],
        }
    if mtype == "ShipStaticData":
        body = ((msg.get("Message") or {}).get("ShipStaticData")) or {}
        return {"wake_vessels": [WakeVessel(
            mmsi=str(mmsi), name=body.get("Name"),
            ship_type=ship_type_label(body.get("Type")),
            callsign=body.get("CallSign"),
            first_seen=now, last_seen=now).model_dump(exclude_none=True)]}
    return {}


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


def flush(root: Path, preset: str, buffer: list[tuple[float, dict]],
          keep_landing: bool = False) -> int:
    """버퍼의 (ts, 메시지)들을 (옵트인) landing + bronze로 배출."""
    if not buffer:
        return 0
    ts = buffer[-1][0]
    if keep_landing:  # 원본 봉투 보존은 옵트인 (--landing)
        _append(_part(root, "landing", SOURCE, "wake", ts=ts),
                [_jsonl({"fetched_at": datetime.fromtimestamp(t, tz=timezone.utc)
                         .strftime("%Y-%m-%dT%H:%M:%SZ"),
                         "source": SOURCE, "kind": "wake",
                         "meta": {"preset": preset}, "payload": msg})
                 for t, msg in buffer])
    tables: dict[str, list[str]] = {}
    for t, msg in buffer:
        for table, rows in to_vessel_and_position(msg, t).items():
            tables.setdefault(table, []).extend(map(_jsonl, rows))
    for table, lines in tables.items():
        _append(_part(root, "bronze", table, f"source={SOURCE}", ts=ts), lines)
    n = len(buffer)
    buffer.clear()
    return n


# ── 수집 (상시 스트림 — 지수 백오프 재접속) ──────────────────────────
async def _default_connect(url: str):
    import websockets

    return await websockets.connect(url)


async def collect(root: Path, api_key: str, preset: str, duration_s: float,
                  keep_landing: bool = False,
                  connect=None, flush_s: float = FLUSH_S) -> int:
    connect = connect or _default_connect
    deadline = time.monotonic() + duration_s if duration_s > 0 else None
    buffer: list[tuple[float, dict]] = []
    total = 0
    backoff = 1.0

    def remaining() -> float | None:
        return None if deadline is None else max(0.0, deadline - time.monotonic())

    while remaining() is None or remaining() > 0:
        try:
            ws = await connect(STREAM_URL)
        except Exception as exc:
            log.warning("connect failed: %s: %s", type(exc).__name__, exc)
            await asyncio.sleep(min(backoff, remaining() or backoff))
            backoff = min(backoff * 2, 60.0)
            continue
        backoff = 1.0
        try:
            await ws.send(json.dumps(subscribe_payload(api_key, preset)))
            last_flush = time.monotonic()
            while remaining() is None or remaining() > 0:
                timeout = flush_s
                if remaining() is not None:
                    timeout = max(0.05, min(flush_s, remaining()))
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                except asyncio.TimeoutError:
                    raw = None
                if raw is not None:
                    try:
                        msg = json.loads(raw)
                        if isinstance(msg, dict):
                            buffer.append((time.time(), msg))
                    except Exception:  # 메시지 건별 격리
                        log.warning("bad message skipped", exc_info=True)
                if time.monotonic() - last_flush >= flush_s or raw is None:
                    total += flush(root, preset, buffer, keep_landing)
                    last_flush = time.monotonic()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("stream dropped: %s: %s", type(exc).__name__, exc)
        finally:
            try:
                await ws.close()
            except Exception:  # noqa: BLE001 — 이미 죽은 소켓
                pass
    total += flush(root, preset, buffer, keep_landing)  # 종료 시 잔여 배출
    log.info("[%s] 메시지 %d개 → %s", SOURCE, total, root)
    return 0


class Preset(str, Enum):
    kr = "kr"
    taiwan = "taiwan"
    sea = "sea"


def cli(
    output: Annotated[Optional[Path], typer.Option(
        help="레이크 루트 (기본: env DATALAKE_ROOT)")] = None,
    duration: Annotated[float, typer.Option(
        help="구독 유지 시간(초). 0 = Ctrl-C까지")] = 0.0,
    preset: Annotated[Preset, typer.Option(help="관심 해역")] = Preset(DEFAULT_PRESET),
    landing: Annotated[bool, typer.Option(
        "--landing", help="원본 봉투를 landing 존에도 보존")] = False,
) -> None:
    """AISStream 스트림 수집 → landing + bronze."""
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    api_key = os.environ.get("DATALAKE_AIS_KEY")
    if not api_key:
        log.error("aisstream 비활성: DATALAKE_AIS_KEY 미설정 (전용 키 필요)")
        raise typer.Exit(2)
    try:
        asyncio.run(collect(output or DEFAULT_ROOT, api_key, preset.value,
                            duration, landing))
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        log.error("실패: %s: %s", type(exc).__name__, exc)
        raise typer.Exit(1)


def main() -> None:
    typer.run(cli)


if __name__ == "__main__":
    main()

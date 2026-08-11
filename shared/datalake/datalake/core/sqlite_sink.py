"""SQLite 옵션 싱크 — raw 존이 진실의 원천, 이 DB는 조회 편의용 파생 존 (설계 §5.2).

전 INSERT가 멱등(OR IGNORE/UPSERT/ts 존재검증)이라 rebuild()로 raw에서
언제든 재구축 가능하다. 레코드 단위 격리: 깨진 레코드가 배치를 못 죽인다.

hub와의 차이(의도): contrail 포지션은 hub의 개체당 300s 게이트 없이 사이클
전량 기록 — 레이크는 밀도가 목적이고 PK(icao24, ts)가 중복을 막는다.
contrail 전세계 스냅샷은 hub와 동일하게 제외(홍수 방지).
"""

from __future__ import annotations

import gzip
import json
import logging
from datetime import datetime
from pathlib import Path

from labkit.archive import Archive

from .. import schema
from ..core.source import Record

log = logging.getLogger("datalake.sqlite")


class SqliteSink:
    def __init__(self, db_path: Path | str) -> None:
        self.archive = Archive(db_path)
        for module, (ddl, tables) in schema.MODULES.items():
            self.archive.ensure_schema(module, ddl, tables)

    def write(self, records) -> None:
        for r in records:
            handler = self._HANDLERS.get(r.source)
            if handler is None:
                continue
            try:
                handler(self, r)
            except Exception:  # 레코드 단위 격리
                log.exception("record failed: %s/%s", r.source, r.kind)

    def close(self) -> None:
        self.archive.close()

    # ── 소스별 핸들러 ─────────────────────────────────────────
    def _quake(self, r: Record) -> None:
        from ..sources.quake import normalize

        self.archive.insert_rows(schema.QUAKE_INSERT, [
            (e["id"], e["mag"], e["place"], e["time"],
             e["lon"], e["lat"], e["depth_km"])
            for e in normalize(r.payload)
        ])

    def _news(self, r: Record) -> None:
        from ..sources.news import normalize

        self.archive.insert_rows(schema.NEWS_INSERT, [
            (a["link"], a["source"], a["title"], a["published"],
             a["summary"], r.fetched_at)
            for a in normalize(r.kind, r.payload)
        ])

    def _trend(self, r: Record) -> None:
        from ..sources.trend import INTERVAL_S, normalize

        items = normalize(r.payload)
        # hub와 동일: ts는 주기 버킷 정렬값 — 재기록·재구축 어느 경로든 멱등
        ts = float(int(r.fetched_at // INTERVAL_S) * INTERVAL_S)
        self.archive.insert_rows(schema.TREND_UPSERT_VIDEO, [
            (i["video_id"], i["title"], i["channel"], i["category_id"],
             i["thumbnail"], i["published_at"], r.fetched_at, r.fetched_at)
            for i in items
        ])
        self.archive.insert_rows(schema.TREND_INSERT_STAT, [
            (i["video_id"], ts, rank, i["view_count"], i["like_count"])
            for rank, i in enumerate(items, start=1)
        ])

    def _contrail(self, r: Record) -> None:
        from ..sources.contrail import normalize

        if r.kind == "global":
            return  # hub와 동일 — 전세계 스냅샷은 아카이브 제외 (홍수 방지)
        flights = normalize(r.payload, now=r.fetched_at)
        self.archive.insert_rows(schema.CONTRAIL_UPSERT_AIRCRAFT, [
            (f["id"], f["callsign"], f["origin_country"], f["ts"], f["ts"])
            for f in flights
        ])
        self.archive.insert_rows(schema.CONTRAIL_INSERT_POSITION, [
            (f["id"], f["ts"], f["lon"], f["lat"], f["alt_m"],
             f["velocity_ms"], f["track_deg"], int(f["on_ground"]))
            for f in flights
        ])

    def _wake(self, r: Record) -> None:
        from ..sources.wake import normalize_position, normalize_static

        msg = r.payload
        mtype = msg.get("MessageType")
        if mtype == "PositionReport":
            point = normalize_position(msg, now=r.fetched_at)
            if point is None:
                return
            self.archive.insert_rows(schema.WAKE_UPSERT_VESSEL, [
                (point["id"], point["name"], None, None,
                 point["ts"], point["ts"]),
            ])
            self.archive.insert_rows(schema.WAKE_INSERT_POSITION, [
                (point["id"], point["ts"], point["lon"], point["lat"],
                 point["sog_kn"], point["cog_deg"], point["heading_deg"]),
            ])
        elif mtype == "ShipStaticData":
            parsed = normalize_static(msg)
            if parsed is None:
                return
            mmsi, meta = parsed
            self.archive.insert_rows(schema.WAKE_UPSERT_VESSEL, [
                (mmsi, meta["name"], meta["ship_type"], meta["callsign"],
                 r.fetched_at, r.fetched_at),
            ])

    def _market(self, r: Record) -> None:
        # hub와 동일하게 snapshots(JSON). ts=fetched_at 존재검증으로 멱등화
        # (snapshots는 키 없는 append 테이블이라 OR IGNORE가 불가능).
        exists = self.archive.query(
            "SELECT 1 FROM snapshots WHERE module=? AND kind=? AND ts=? LIMIT 1",
            ("market", r.kind, r.fetched_at),
        )
        if not exists:
            self.archive.put_snapshot("market", r.kind, r.payload,
                                      ts=r.fetched_at)

    _HANDLERS = {
        "quake": _quake,
        "news": _news,
        "trend": _trend,
        "contrail": _contrail,
        "wake": _wake,
        "market": _market,
    }


def _iter_lake(root: Path):
    """raw 존 전체를 시간순으로 순회하며 Record를 재생한다 (.jsonl / .jsonl.gz)."""
    for path in sorted((root / "raw").glob("*/*/dt=*/part-*.jsonl*")):
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    env = json.loads(line)
                    fetched = datetime.fromisoformat(
                        env["fetched_at"].replace("Z", "+00:00")).timestamp()
                    yield Record(
                        source=env["source"], kind=env["kind"],
                        payload=env["payload"], meta=env.get("meta") or {},
                        fetched_at=fetched,
                    )
                except Exception:  # 깨진 줄 격리
                    log.warning("skipping bad line in %s", path, exc_info=True)


def rebuild(root: Path, db_path: Path | str,
            sources: set[str] | None = None) -> int:
    """raw 레이크 → SQLite 재구축. 처리한 레코드 수 반환. 멱등."""
    sink = SqliteSink(db_path)
    count = 0
    try:
        batch: list[Record] = []
        for rec in _iter_lake(Path(root)):
            if sources and rec.source not in sources:
                continue
            batch.append(rec)
            count += 1
            if len(batch) >= 500:
                sink.write(batch)
                batch = []
        sink.write(batch)
    finally:
        sink.close()
    return count

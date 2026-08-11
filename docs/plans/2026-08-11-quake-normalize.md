# Quake 아카이브 정규화 전환 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** quake 아카이브를 JSON `entities`에서 정규화 `quake_events` 테이블로 전환하고, 기존 행을 startup 멱등 마이그레이션으로 백필·정리한다.

**Architecture:** contrail/wake 정규화 패턴의 축소판 — 모듈 로컬 `schema.py`(DDL·SQL 상수) + `migrate.py`(멱등 백필) + collector 기록 경로 1곳 교체. 삭제는 "quake_events에 실재하는 id만" 단일 DELETE로 완전 멱등. labkit·API·프론트 무변경.

**Tech Stack:** Python 3.11/FastAPI, labkit Archive 정규화 확장(ensure_schema/insert_rows/query), pytest(tmp DB + monkeypatch).

**Spec:** `docs/specs/2026-08-11-quake-normalize-design.md`

## Global Constraints

- 저장소 루트 `/Users/joonjeong/claude-lab`. 커밋은 루트에서. 실행 워크스페이스가 워크트리면 그 안에서만 작업.
- 아카이브는 전 구간 best-effort — 마이그레이션·기록 실패가 모듈 기동·수집을 절대 막지 않는다 (hub `app/archive.py` 헬퍼 경유).
- `INSERT OR IGNORE` 멱등 계약 유지. `time`은 epoch ms INTEGER (기존 normalize 계약).
- 비정상 entities 행(JSON 파싱·키 누락)은 경고 로그 후 스킵하고 **entities에서 삭제하지 않는다**.
- 삭제 판정은 INSERT rowcount가 아니라 존재 검증: `DELETE ... WHERE id IN (SELECT id FROM quake_events)` (스펙 §3 — rowcount는 중복 재실행 시 0이라 사용 금지).
- quake_events는 프루닝 없음 (`register_prune` 미사용).
- 테스트: `uv run --directory hub/backend pytest tests/ -v` — 기존 22개 그린 유지.
- `shared/labkit.egg-info/*`가 dirty로 보여도 커밋 금지 (빌드 아티팩트).

---

### Task 1: schema.py + migrate.py (멱등 백필)

**Files:**
- Create: `hub/backend/app/modules/quake/schema.py`
- Create: `hub/backend/app/modules/quake/migrate.py`
- Test: `hub/backend/tests/test_quake_migrate.py`

**Interfaces:**
- Consumes: `labkit.Archive`(ensure_schema/put_entities/insert_rows/query — 기존), hub `app/archive.py`의 `archive_insert(sql, rows) -> int`, `archive_query(sql, params=()) -> list[tuple]` (모듈 전역 `archive` 인스턴스를 호출 시점에 참조하므로 monkeypatch 가능)
- Produces: `schema.DDL: str`, `schema.TABLES = ["quake_events"]`, `schema.INSERT_EVENT: str`(7컬럼), `schema.DELETE_MIGRATED: str`, `migrate.migrate_entities() -> int`(파싱 성공 건수 반환)

- [ ] **Step 1: 실패하는 테스트 작성**

`hub/backend/tests/test_quake_migrate.py`:

```python
"""quake entities JSON → quake_events 멱등 백필: 이관·삭제·격리·멱등성."""
from labkit import Archive

import app.archive as hub_archive
from app.modules.quake import schema
from app.modules.quake.migrate import migrate_entities

EVENT = {
    "id": "ev1", "mag": 4.5, "place": "somewhere, Alaska",
    "time": 1_786_300_000_000, "lon": -148.9, "lat": 62.2, "depth_km": 10.0,
}


def make_archive(tmp_path, monkeypatch) -> Archive:
    a = Archive(tmp_path / "t.db")
    a.ensure_schema("quake", schema.DDL, schema.TABLES)
    monkeypatch.setattr(hub_archive, "archive", a)  # 헬퍼가 이 인스턴스를 쓰게
    return a


def test_backfill_moves_rows_and_deletes_source(tmp_path, monkeypatch):
    a = make_archive(tmp_path, monkeypatch)
    a.put_entities("quake", [("ev1", EVENT), ("ev2", {**EVENT, "id": "ev2"})])
    assert migrate_entities() == 2
    assert a.query("SELECT COUNT(*) FROM quake_events")[0][0] == 2
    assert a.query("SELECT COUNT(*) FROM entities WHERE module='quake'")[0][0] == 0
    # 컬럼 매핑 검증 (id, mag, place, time, lon, lat, depth_km)
    row = a.query(
        "SELECT mag, place, time, lon, lat, depth_km FROM quake_events WHERE id='ev1'"
    )[0]
    assert row == (4.5, "somewhere, Alaska", 1_786_300_000_000, -148.9, 62.2, 10.0)


def test_idempotent_rerun_and_empty_noop(tmp_path, monkeypatch):
    a = make_archive(tmp_path, monkeypatch)
    a.put_entities("quake", [("ev1", EVENT)])
    migrate_entities()
    assert migrate_entities() == 0  # entities 비었으니 no-op
    assert a.query("SELECT COUNT(*) FROM quake_events")[0][0] == 1


def test_malformed_rows_skipped_and_kept(tmp_path, monkeypatch):
    a = make_archive(tmp_path, monkeypatch)
    a.put_entities("quake", [("good", EVENT)])
    # put_entities는 JSON을 강제하므로 비정상 payload는 직접 삽입
    a.insert_rows(
        "INSERT OR IGNORE INTO entities (module, id, first_seen, payload)"
        " VALUES (?, ?, ?, ?)",
        [("quake", "bad-json", 0.0, "not-json"),
         ("quake", "bad-keys", 0.0, '{"id":"bad-keys"}')],  # mag 등 누락 → KeyError
    )
    assert migrate_entities() == 1  # good만 파싱 성공
    ids = {r[0] for r in a.query("SELECT id FROM quake_events")}
    assert ids == {"good"}
    kept = {r[0] for r in a.query("SELECT id FROM entities WHERE module='quake'")}
    assert kept == {"bad-json", "bad-keys"}  # 비정상 행은 보존


def test_other_module_rows_untouched(tmp_path, monkeypatch):
    a = make_archive(tmp_path, monkeypatch)
    a.put_entities("news", [("article1", {"title": "x"})])
    a.put_entities("quake", [("ev1", EVENT)])
    migrate_entities()
    assert a.query("SELECT COUNT(*) FROM entities WHERE module='news'")[0][0] == 1
```

- [ ] **Step 2: 실패 확인**

Run: `uv run --directory hub/backend pytest tests/test_quake_migrate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.modules.quake.schema'`

- [ ] **Step 3: schema.py 작성**

`hub/backend/app/modules/quake/schema.py`:

```python
"""Quake 정규화 스키마 — 점 이벤트 단일 테이블 (dim/fact 분리 없음, 스펙 §1)."""

DDL = """
CREATE TABLE IF NOT EXISTS quake_events (
  id       TEXT PRIMARY KEY,
  mag      REAL,
  place    TEXT,
  time     INTEGER,
  lon      REAL,
  lat      REAL,
  depth_km REAL
);
CREATE INDEX IF NOT EXISTS idx_quake_events_time ON quake_events (time);
"""

TABLES = ["quake_events"]

INSERT_EVENT = """
INSERT OR IGNORE INTO quake_events (id, mag, place, time, lon, lat, depth_km)
VALUES (?, ?, ?, ?, ?, ?, ?)
"""

# quake_events에 실재하는 id만 삭제 — INSERT OR IGNORE rowcount는 중복 재실행 시
# 0이라 성공 판정에 쓸 수 없다 (스펙 §3). 이관 실패 행은 구조적으로 삭제 불가.
DELETE_MIGRATED = """
DELETE FROM entities
 WHERE module = 'quake' AND id IN (SELECT id FROM quake_events)
"""
```

- [ ] **Step 4: migrate.py 작성**

`hub/backend/app/modules/quake/migrate.py`:

```python
"""entities JSON → quake_events 멱등 백필 (startup에서 매번 호출, 빈 상태면 no-op).

비정상 행(JSON 파싱·키 누락)은 경고 로그 후 스킵하고 entities에 남긴다 —
원본이 유일한 사본이므로 삭제하지 않는다 (스펙 확정 결정).
"""
from __future__ import annotations

import json
import logging

from ...archive import archive_insert, archive_query
from . import schema

logger = logging.getLogger(__name__)


def migrate_entities() -> int:
    """파싱에 성공해 INSERT 배치에 포함된 건수를 반환. best-effort."""
    rows = archive_query(
        "SELECT id, payload FROM entities WHERE module = 'quake'"
    )
    if not rows:
        return 0
    events: list[tuple] = []
    for eid, payload in rows:
        try:
            e = json.loads(payload)
            events.append((
                str(eid), float(e["mag"]), str(e["place"]), int(e["time"]),
                float(e["lon"]), float(e["lat"]), float(e["depth_km"]),
            ))
        except Exception:  # 한 행의 비정상이 나머지를 막지 않는다
            logger.warning(
                "quake migrate: skipping malformed entities row %r",
                eid, exc_info=True,
            )
    inserted = archive_insert(schema.INSERT_EVENT, events)
    deleted = archive_insert(schema.DELETE_MIGRATED, [()])  # 인자 없는 단일 실행
    logger.info(
        "quake migrate: %d parsed, %d inserted, %d entities rows deleted",
        len(events), inserted, deleted,
    )
    return len(events)
```

- [ ] **Step 5: 통과 확인**

Run: `uv run --directory hub/backend pytest tests/test_quake_migrate.py -v`
Expected: 4 PASS. 이어서 전체: `uv run --directory hub/backend pytest tests/ -v` → 26 PASS.

- [ ] **Step 6: Commit**

```bash
git add hub/backend/app/modules/quake/schema.py hub/backend/app/modules/quake/migrate.py hub/backend/tests/test_quake_migrate.py
git commit -m "quake: 정규화 스키마 + entities 멱등 백필 마이그레이션"
```

---

### Task 2: collector 기록 경로 전환 + startup 편입

**Files:**
- Modify: `hub/backend/app/modules/quake/collector.py` (import 1곳 + `_on_result` 1곳)
- Modify: `hub/backend/app/modules/quake/__init__.py` (`startup()`)

**Interfaces:**
- Consumes: Task 1의 `schema.INSERT_EVENT`/`DDL`/`TABLES`, `migrate.migrate_entities()`, hub `archive_insert`/`archive_ensure_schema`
- Produces: quake 모듈이 quake_events에만 기록하는 최종 상태 (hub 계약 무변경)

- [ ] **Step 1: collector.py 전환**

`hub/backend/app/modules/quake/collector.py`에서:

기존:
```python
from ...archive import archive_entities
```
→
```python
from ...archive import archive_insert
```
(그리고 상단 import에 `from . import config, schema`가 되도록 `schema` 추가 —
현재는 `from . import config`.)

기존 `_on_result`:
```python
def _on_result(events: list[dict]) -> None:
    store.ingest(events)
    # 이력 아카이브 (best-effort) — id PK의 INSERT OR IGNORE가 재관측을 걸러낸다
    archive_entities("quake", [(e["id"], e) for e in events])
```
→
```python
def _on_result(events: list[dict]) -> None:
    store.ingest(events)
    # 정규화 아카이브 (best-effort) — id PK의 INSERT OR IGNORE가 재관측을 걸러낸다
    archive_insert(schema.INSERT_EVENT, [
        (e["id"], e["mag"], e["place"], e["time"], e["lon"], e["lat"], e["depth_km"])
        for e in events
    ])
```

- [ ] **Step 2: `__init__.py` startup 편입**

`hub/backend/app/modules/quake/__init__.py`:

기존:
```python
from .api import health, router
from .collector import collector
```
→
```python
from ...archive import archive_ensure_schema
from . import schema
from .api import health, router
from .collector import collector
from .migrate import migrate_entities
```

기존 `startup()`:
```python
async def startup() -> None:
    collector.start()
```
→
```python
async def startup() -> None:
    archive_ensure_schema("quake", schema.DDL, schema.TABLES)
    migrate_entities()  # entities 잔여분 멱등 백필 (비면 no-op)
    collector.start()
```

- [ ] **Step 3: 전체 테스트**

Run: `uv run --directory hub/backend pytest tests/ -v`
Expected: 26 PASS (기존 22 + Task 1의 4).

- [ ] **Step 4: 실 DB 검증**

사전 상태 확인 후 서버 기동으로 실제 마이그레이션 확인:

```bash
sqlite3 hub/backend/data/lab.db "SELECT COUNT(*) FROM entities WHERE module='quake'"   # 기대: 76 (±수집분)
(cd hub/backend && uv run uvicorn app.main:app --port 8010 &) && sleep 8
sqlite3 hub/backend/data/lab.db "SELECT COUNT(*) FROM quake_events"                     # 기대: ≥76
sqlite3 hub/backend/data/lab.db "SELECT COUNT(*) FROM entities WHERE module='quake'"   # 기대: 0
curl -s localhost:8010/healthz | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["archive"])'
#   archive.quake가 quake_events 기준으로 집계 (counts()의 레지스트리 경로)
kill %1
```

60초 뒤 재조회 시 quake_events가 증가하면 신규 기록 경로도 확인된 것 (선택).

- [ ] **Step 5: Commit**

```bash
git add hub/backend/app/modules/quake/collector.py hub/backend/app/modules/quake/__init__.py
git commit -m "quake: 아카이브 기록 경로를 quake_events로 전환 — startup 멱등 백필 편입"
```

---

## Self-Review 결과

- **스펙 커버리지**: §1 스키마=Task 1 Step 3, §2 기록 전환=Task 2 Step 1, §3 마이그레이션=Task 1 Step 4 + Task 2 Step 2, §4 에러=migrate 건별 격리·존재 검증 DELETE, §5 테스트=Task 1 Step 1 (4케이스 전부), §6 검증=Task 2 Step 4. 범위 밖 항목 침범 없음.
- **플레이스홀더**: 없음.
- **타입 일관성**: `migrate_entities() -> int`, `archive_insert(sql, rows) -> int`, `archive_query(sql, params=()) -> list[tuple]`, INSERT_EVENT 7컬럼 순서가 테스트 assert·collector 튜플과 일치 확인.

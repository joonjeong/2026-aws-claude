# Contrail Watch ✈️ + Wake Watch 🌊 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** hub에 항공(contrail, OpenSky 폴링)·해상(wake, AISStream WebSocket) 이동 경로 모니터 모듈 2개를 추가한다 — 개체별 6시간 trail + 정규화 SQLite 아카이브 + 한국어 LLM 브리핑.

**Architecture:** labkit에 공용 3종(TrailStore, StreamCollector, Archive 정규화 확장)을 추가하고, 두 모듈은 quake 모듈 패턴(META/router/startup/shutdown/health 계약)을 따르는 얇은 조립층으로 만든다. 프론트는 공용 GeoCanvas(SVG 지도 베이스 + bbox 줌) 위에 앱 2개.

**Tech Stack:** Python 3.11+/FastAPI/httpx/websockets/sqlite3, pytest(+pytest-asyncio), React 18/Vite(가상 `virtual:apps` 레지스트리), Bedrock converse REST(labkit).

**Spec:** `docs/specs/2026-08-11-contrail-wake-design.md` — 모든 수치·계약의 원본.

## Global Constraints

- 저장소 루트는 `/Users/joonjeong/claude-lab`. 모든 경로는 루트 기준. 커밋은 루트에서.
- hub 모듈 계약(`hub/backend/app/modules/__init__.py`): 각 모듈은 `META, router, startup(), shutdown(), health()`를 노출. main.py는 무변경.
- 단일 asyncio 이벤트 루프 전제 — 스토어에 락 없음 (labkit stores.py 관례).
- 에러 계약: LLM 토큰 미설정 → 503, 업스트림 오류 → 502(상태코드만 노출). 아카이브는 전 구간 best-effort(실패는 로그만).
- 수집 격리: 폴링 사이클·스트림 메시지·정규화 건별 try/except — 한 건의 비정상이 나머지를 죽이지 않는다.
- 키는 환경변수로만: `CONTRAIL_OPENSKY_CLIENT_ID/SECRET`, `WAKE_AIS_KEY`, `AWS_BEARER_TOKEN_BEDROCK`. 코드·리포지토리에 값 없음.
- trail 창 6시간(21,600초), trail 다운샘플 gap 60초 + 이동 0.5km(contrail 1.0km), 아카이브 gap 300초, fact 보존 7일. 전부 env 오버라이드.
- 정규화 테이블만 사용 (`*_positions`/`*_aircraft`/`*_vessels`) — 신규 모듈은 JSON payload `entities`/`snapshots`에 쓰지 않는다.
- quake 모듈·앱은 이번 작업에서 수정 금지 (frontend CONTINENTS 복사는 허용, 원본 무변경).
- 테스트 실행: `uv run --directory hub/backend pytest tests/ -v` (labkit은 editable 설치라 함께 테스트).
- 프론트 검증: `cd hub/frontend && pnpm build` (tsc --noEmit 포함).
- 파이썬 파일 첫 줄 docstring + 한국어/영어 혼용 주석은 기존 파일 스타일을 따른다.

---

### Task 1: labkit TrailStore

**Files:**
- Create: `shared/labkit/trails.py`
- Modify: `shared/labkit/__init__.py` (export 추가)
- Modify: `hub/backend/pyproject.toml` (pytest dev 의존성)
- Test: `hub/backend/tests/test_trails.py`

**Interfaces:**
- Consumes: 없음 (stdlib만)
- Produces: `TrailStore(window_s, gap_s, min_move_km, stale_s, max_entities)` —
  `ingest(point: dict) -> bool`(trail 점 추가 여부), `merge_meta(id, meta) -> bool`,
  `entities() -> list[dict]`, `trails(min_points=2) -> list[dict]`,
  `prune(now=None) -> None`, `reset() -> None`, `__len__`, `last_ingest: float | None`.
  point 필수 키: `id, ts, lon, lat` (+임의 확장 키는 latest에 병합).

- [ ] **Step 1: pytest dev 의존성 추가**

`hub/backend/pyproject.toml` 끝에 추가:

```toml
[dependency-groups]
dev = ["pytest>=8", "pytest-asyncio>=0.24"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

Run: `uv sync --directory hub/backend`
Expected: pytest 설치 완료.

- [ ] **Step 2: 실패하는 테스트 작성**

`hub/backend/tests/__init__.py` 빈 파일 생성. `hub/backend/tests/test_trails.py`:

```python
"""TrailStore: 다운샘플링·창 프루닝·퇴출 규칙 검증. 시간은 전부 명시 주입."""
from labkit.trails import TrailStore


def _pt(eid="a", ts=0.0, lon=127.0, lat=37.0, **extra):
    return {"id": eid, "ts": ts, "lon": lon, "lat": lat, **extra}


def make_store(**kw):
    defaults = dict(window_s=21_600, gap_s=60, min_move_km=0.5,
                    stale_s=900, max_entities=5)
    defaults.update(kw)
    return TrailStore(**defaults)


def test_first_point_appends_and_latest_merges_extras():
    s = make_store()
    assert s.ingest(_pt(ts=0, sog_kn=10.5)) is True
    assert len(s) == 1
    latest = s.entities()[0]
    assert latest["sog_kn"] == 10.5 and latest["id"] == "a"
    # 단일 점 trail은 trails()에서 제외 (min_points=2)
    assert s.trails() == []


def test_downsample_requires_gap_and_move():
    s = make_store()
    s.ingest(_pt(ts=0))
    # gap 미충족 (59초) — 크게 움직여도 미추가
    assert s.ingest(_pt(ts=59, lon=128.0)) is False
    # gap 충족 + 이동 미충족 (제자리) — 미추가, latest는 갱신됨
    assert s.ingest(_pt(ts=120, lon=127.0, sog_kn=0.1)) is False
    assert s.entities()[0]["sog_kn"] == 0.1
    # gap + 이동(경도 0.1도 ≈ 8.9km) 충족 — 추가
    assert s.ingest(_pt(ts=180, lon=127.1)) is True
    assert s.trails()[0]["points"] == [[0, 127.0, 37.0], [180, 127.1, 37.0]]


def test_window_pruning_drops_old_points():
    s = make_store(window_s=100, gap_s=10, min_move_km=0.0)
    s.ingest(_pt(ts=0))
    s.ingest(_pt(ts=50, lon=127.1))
    s.ingest(_pt(ts=140, lon=127.2))  # cutoff=40 → ts=0 탈락
    pts = s.trails()[0]["points"]
    assert [p[0] for p in pts] == [50, 140]


def test_stale_eviction_and_capacity():
    s = make_store(max_entities=2)
    s.ingest(_pt("a", ts=0))
    s.ingest(_pt("b", ts=100))
    s.prune(now=950)  # a는 950-0 > 900 → 퇴출, b 생존
    assert len(s) == 1
    s.ingest(_pt("c", ts=1000))
    s.ingest(_pt("d", ts=1100))  # 상한 2 초과 → 가장 오래된 b 퇴출
    ids = {e["id"] for e in s.entities()}
    assert ids == {"c", "d"}


def test_merge_meta_only_for_known_entity():
    s = make_store()
    assert s.merge_meta("ghost", {"name": "X"}) is False
    s.ingest(_pt("a", ts=0))
    assert s.merge_meta("a", {"name": "EVER GIVEN"}) is True
    assert s.entities()[0]["name"] == "EVER GIVEN"


def test_reset_empties_everything():
    s = make_store()
    s.ingest(_pt(ts=0))
    s.reset()
    assert len(s) == 0 and s.entities() == []
```

- [ ] **Step 3: 실패 확인**

Run: `uv run --directory hub/backend pytest tests/test_trails.py -v`
Expected: FAIL — `ModuleNotFoundError: labkit.trails`

- [ ] **Step 4: 구현**

`shared/labkit/trails.py`:

```python
"""Per-entity position history for moving objects (ships, aircraft).

quake's IdempotentStore keys point events; TrailStore keys *entities* and
keeps a downsampled trail per entity. A trail point is appended only when
BOTH thresholds pass — gap_s elapsed since the last kept point AND
min_move_km moved — so an anchored ship stays a single point while its
`latest` keeps refreshing. Single asyncio event loop assumed — no locks.
"""
from __future__ import annotations

import math
import time
from collections import deque


def dist_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Equirectangular approximation — plenty for threshold checks."""
    x = math.radians(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    y = math.radians(lat2 - lat1)
    return 6371.0 * math.hypot(x, y)


class TrailStore:
    def __init__(
        self,
        window_s: float = 21_600.0,
        gap_s: float = 60.0,
        min_move_km: float = 0.5,
        stale_s: float = 900.0,
        max_entities: int = 5_000,
    ) -> None:
        self.window_s = window_s
        self.gap_s = gap_s
        self.min_move_km = min_move_km
        self.stale_s = stale_s
        self.max_entities = max_entities
        self._items: dict[str, dict] = {}  # id → {"latest": dict, "trail": deque}
        self.last_ingest: float | None = None  # wall clock of last ingest

    def ingest(self, point: dict) -> bool:
        """Update latest (merge keys); append trail point per downsample rule.
        Returns True iff a trail point was appended (archive gate uses this)."""
        eid = point["id"]
        entry = self._items.get(eid)
        if entry is None:
            entry = self._items[eid] = {"latest": {}, "trail": deque()}
            if len(self._items) > self.max_entities:
                self._evict_overflow()
        entry["latest"].update(point)
        self.last_ingest = time.time()

        trail: deque = entry["trail"]
        added = False
        if not trail:
            trail.append((point["ts"], point["lon"], point["lat"]))
            added = True
        else:
            last_ts, last_lon, last_lat = trail[-1]
            if point["ts"] - last_ts >= self.gap_s and (
                dist_km(last_lon, last_lat, point["lon"], point["lat"])
                >= self.min_move_km
            ):
                trail.append((point["ts"], point["lon"], point["lat"]))
                added = True
        cutoff = point["ts"] - self.window_s
        while trail and trail[0][0] < cutoff:
            trail.popleft()
        return added

    def merge_meta(self, eid: str, meta: dict) -> bool:
        """Merge slow-changing metadata (ship name/type). Unknown id → False."""
        entry = self._items.get(eid)
        if entry is None:
            return False
        entry["latest"].update(meta)
        return True

    def entities(self) -> list[dict]:
        return [e["latest"] for e in self._items.values()]

    def trails(self, min_points: int = 2) -> list[dict]:
        return [
            {"id": eid, "points": [list(p) for p in e["trail"]]}
            for eid, e in self._items.items()
            if len(e["trail"]) >= min_points
        ]

    def prune(self, now: float | None = None) -> None:
        """Evict entities unobserved for stale_s (by their last point ts)."""
        now = time.time() if now is None else now
        doomed = [
            eid
            for eid, e in self._items.items()
            if now - e["latest"]["ts"] > self.stale_s
        ]
        for eid in doomed:
            del self._items[eid]

    def _evict_overflow(self) -> None:
        overflow = len(self._items) - self.max_entities
        if overflow <= 0:
            return
        ranked = sorted(self._items, key=lambda k: self._items[k]["latest"]["ts"])
        for eid in ranked[:overflow]:
            del self._items[eid]

    def reset(self) -> None:
        self._items.clear()

    def __len__(self) -> int:
        return len(self._items)
```

`shared/labkit/__init__.py`에 export 추가 — import 블록에 `from .trails import TrailStore` 한 줄, `__all__`에 `"TrailStore"` 추가.

- [ ] **Step 5: 통과 확인**

Run: `uv run --directory hub/backend pytest tests/test_trails.py -v`
Expected: 6 PASS

- [ ] **Step 6: Commit**

```bash
git add shared/labkit/trails.py shared/labkit/__init__.py hub/backend/pyproject.toml hub/backend/uv.lock hub/backend/tests/
git commit -m "labkit: TrailStore — 이동 개체 경로 이력 + 임계값 다운샘플링"
```

---

### Task 2: labkit Archive 정규화 확장

**Files:**
- Modify: `shared/labkit/archive.py`
- Modify: `hub/backend/app/archive.py` (best-effort 헬퍼 + 프루닝 레지스트리)
- Test: `hub/backend/tests/test_archive_schema.py`

**Interfaces:**
- Consumes: 기존 `Archive` (entities/snapshots 무변경 유지)
- Produces (labkit.Archive 메서드):
  - `ensure_schema(module: str, ddl: str, tables: list[str]) -> None` — DDL 실행 + `{table→module}` 레지스트리 등록
  - `insert_rows(sql: str, rows: list[tuple]) -> int` — executemany+commit, 빈 rows는 0
  - `query(sql: str, params: tuple = ()) -> list[tuple]`
  - `prune_table(table: str, ts_col: str, days: int) -> int` — 등록 안 된 테이블/days<=0은 0
  - `counts()` 확장 — 등록된 정규화 테이블 행수도 모듈별 합산
- Produces (hub `app/archive.py` 함수, 모듈이 쓰는 best-effort 래퍼):
  - `archive_ensure_schema(module, ddl, tables) -> None`
  - `archive_insert(sql, rows) -> int` (실패 시 0)
  - `archive_query(sql, params) -> list[tuple]` (실패 시 [])
  - `register_prune(table, ts_col, days) -> None` — 기존 24h prune_poller 틱에 편입

- [ ] **Step 1: 실패하는 테스트 작성**

`hub/backend/tests/test_archive_schema.py`:

```python
"""Archive 정규화 확장: 모듈 정의 테이블 등록·기록·조회·프루닝."""
import time

from labkit import Archive

DDL = """
CREATE TABLE IF NOT EXISTS t_vessels (
  mmsi TEXT PRIMARY KEY, name TEXT, first_seen REAL NOT NULL, last_seen REAL NOT NULL);
CREATE TABLE IF NOT EXISTS t_positions (
  mmsi TEXT NOT NULL, ts REAL NOT NULL, lon REAL NOT NULL, lat REAL NOT NULL,
  PRIMARY KEY (mmsi, ts));
"""

UPSERT = """
INSERT INTO t_vessels (mmsi, name, first_seen, last_seen) VALUES (?, ?, ?, ?)
ON CONFLICT(mmsi) DO UPDATE SET
  last_seen = excluded.last_seen,
  name = COALESCE(excluded.name, t_vessels.name)
"""


def make(tmp_path):
    a = Archive(tmp_path / "t.db")
    a.ensure_schema("testmod", DDL, ["t_vessels", "t_positions"])
    return a


def test_insert_query_and_counts(tmp_path):
    a = make(tmp_path)
    n = a.insert_rows(
        "INSERT OR IGNORE INTO t_positions (mmsi, ts, lon, lat) VALUES (?, ?, ?, ?)",
        [("1", 1.0, 127.0, 37.0), ("1", 2.0, 127.1, 37.0)],
    )
    assert n == 2
    assert a.insert_rows("INSERT OR IGNORE INTO t_positions VALUES (?, ?, ?, ?)", []) == 0
    rows = a.query("SELECT ts, lon FROM t_positions WHERE mmsi = ? ORDER BY ts", ("1",))
    assert [r[0] for r in rows] == [1.0, 2.0]
    assert a.counts().get("testmod") == 2


def test_dim_upsert_keeps_first_seen_and_fills_name(tmp_path):
    a = make(tmp_path)
    a.insert_rows(UPSERT, [("9", None, 100.0, 100.0)])
    a.insert_rows(UPSERT, [("9", "EVER GIVEN", 100.0, 200.0)])
    a.insert_rows(UPSERT, [("9", None, 100.0, 300.0)])  # None이 이름을 지우면 안 됨
    row = a.query("SELECT name, first_seen, last_seen FROM t_vessels WHERE mmsi='9'")[0]
    assert row == ("EVER GIVEN", 100.0, 300.0)


def test_prune_table_by_retention(tmp_path):
    a = make(tmp_path)
    old = time.time() - 10 * 86_400
    a.insert_rows(
        "INSERT OR IGNORE INTO t_positions (mmsi, ts, lon, lat) VALUES (?, ?, ?, ?)",
        [("1", old, 0, 0), ("1", time.time(), 0, 0)],
    )
    assert a.prune_table("t_positions", "ts", 7) == 1
    assert a.prune_table("t_positions", "ts", 0) == 0        # disabled
    assert a.prune_table("unregistered", "ts", 7) == 0       # 미등록 테이블 거부
```

- [ ] **Step 2: 실패 확인**

Run: `uv run --directory hub/backend pytest tests/test_archive_schema.py -v`
Expected: FAIL — `AttributeError: 'Archive' object has no attribute 'ensure_schema'`

- [ ] **Step 3: labkit 구현**

`shared/labkit/archive.py` — `__init__`에 `self._tables: dict[str, str] = {}` 추가하고, 클래스에 메서드 4개 추가 + `counts()` 교체:

```python
    # --- module-defined normalized tables (dim/fact) ---------------------

    def ensure_schema(self, module: str, ddl: str, tables: list[str]) -> None:
        """Run a module's DDL (CREATE IF NOT EXISTS) and register its tables
        so counts()/prune_table() know them. Idempotent."""
        self._conn.executescript(ddl)
        self._conn.commit()
        for t in tables:
            self._tables[t] = module

    def insert_rows(self, sql: str, rows: list[tuple]) -> int:
        if not rows:
            return 0
        cur = self._conn.executemany(sql, rows)
        self._conn.commit()
        return cur.rowcount

    def query(self, sql: str, params: tuple = ()) -> list[tuple]:
        return self._conn.execute(sql, params).fetchall()

    def prune_table(self, table: str, ts_col: str, days: int) -> int:
        """Delete rows older than `days` from a REGISTERED table only —
        the registry doubles as an identifier allowlist (no SQL injection
        via table/column names)."""
        if days <= 0 or table not in self._tables:
            return 0
        cur = self._conn.execute(
            f"DELETE FROM {table} WHERE {ts_col} < ?",  # noqa: S608 — allowlisted
            (time.time() - days * 86_400,),
        )
        self._conn.commit()
        return cur.rowcount
```

`counts()`는 기존 두 테이블 집계 뒤에 정규화 테이블 집계를 덧붙인다 (기존 본문 유지 + 아래 추가):

```python
        for table, module in self._tables.items():
            (n,) = self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()  # noqa: S608
            out[module] = out.get(module, 0) + n
```

주의: `prune_table`의 `ts_col`도 등록 테이블에만 적용되지만 컬럼명은 검증하지 않는다 — 호출자는 모듈 자신의 schema.py 상수만 넘긴다(외부 입력 아님).

- [ ] **Step 4: hub 헬퍼 구현**

`hub/backend/app/archive.py`에 추가 (기존 헬퍼 아래):

```python
# --- 정규화 테이블 경로 (contrail/wake, 이후 quake 전환도 이 경로) ---------

_PRUNE_SPECS: list[tuple[str, str, int]] = []  # (table, ts_col, days)


def archive_ensure_schema(module: str, ddl: str, tables: list[str]) -> None:
    try:
        archive.ensure_schema(module, ddl, tables)
    except Exception:  # noqa: BLE001 — best-effort: 모듈 기동을 깨지 않는다
        log.exception("archive ensure_schema failed (module=%s)", module)


def archive_insert(sql: str, rows: list[tuple]) -> int:
    try:
        return archive.insert_rows(sql, rows)
    except Exception:  # noqa: BLE001 — best-effort
        log.exception("archive insert failed")
        return 0


def archive_query(sql: str, params: tuple = ()) -> list[tuple]:
    try:
        return archive.query(sql, params)
    except Exception:  # noqa: BLE001 — 조회 실패는 빈 결과로
        log.exception("archive query failed")
        return []


def register_prune(table: str, ts_col: str, days: int) -> None:
    spec = (table, ts_col, days)
    if spec not in _PRUNE_SPECS:
        _PRUNE_SPECS.append(spec)
```

그리고 `_prune_tick()` 본문 끝에 추가:

```python
    for table, ts_col, days in _PRUNE_SPECS:
        n = archive.prune_table(table, ts_col, days)
        if n:
            log.info("archive pruned %d rows from %s (>%dd)", n, table, days)
```

(반환값 `deleted`는 기존대로 snapshots 것만 유지해도 된다 — 로그가 목적.)

- [ ] **Step 5: 통과 확인**

Run: `uv run --directory hub/backend pytest tests/ -v`
Expected: Task 1 포함 전체 PASS

- [ ] **Step 6: Commit**

```bash
git add shared/labkit/archive.py hub/backend/app/archive.py hub/backend/tests/test_archive_schema.py
git commit -m "labkit/hub: 아카이브 정규화 테이블 지원 — 모듈 DDL 등록·기록·프루닝"
```

---

### Task 3: labkit StreamCollector

**Files:**
- Create: `shared/labkit/stream.py`
- Modify: `shared/labkit/__init__.py`, `shared/pyproject.toml` (websockets 의존성)
- Test: `hub/backend/tests/test_stream.py`

**Interfaces:**
- Consumes: 없음
- Produces: `StreamCollector(name, url, on_message: Callable[[dict], None], subscribe: Callable[[], dict] | None = None, backoff_initial_s=1.0, backoff_max_s=60.0, connect=None)` —
  `start() -> asyncio.Task`, `stop() -> None`, `resubscribe() -> None`,
  `status: dict` 프로퍼티 `{name, connected, last_msg_at, msg_count, reconnects, last_error}`.
  `connect(url)`은 테스트 주입용 — `send(str)`, `async for`, `close()`를 가진 객체를 반환하는 async 콜러블 (기본: `websockets.connect`).

- [ ] **Step 1: websockets 의존성 추가**

`shared/pyproject.toml` dependencies를 `["httpx>=0.27", "websockets>=12"]`로 변경.

Run: `uv sync --directory hub/backend`
Expected: websockets 설치.

- [ ] **Step 2: 실패하는 테스트 작성**

`hub/backend/tests/test_stream.py`:

```python
"""StreamCollector: 구독 전송·메시지 격리·재접속 백오프 — fake ws로 검증."""
import asyncio
import json

from labkit.stream import StreamCollector


class FakeWS:
    def __init__(self, messages):
        self.sent: list[str] = []
        self._messages = list(messages)
        self.closed = False

    async def send(self, data):
        self.sent.append(data)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._messages:
            await asyncio.sleep(3600)  # 연결 유지 상태 흉내 (stop()이 취소)
        return self._messages.pop(0)

    async def close(self):
        self.closed = True


async def test_subscribe_sent_and_bad_message_isolated():
    ws = FakeWS(['{"MessageType":"PositionReport"}', "not-json", '{"a":1}'])
    got = []

    async def connect(url):
        return ws

    c = StreamCollector(
        "t", "wss://x", got.append,
        subscribe=lambda: {"APIKey": "k"}, connect=connect,
    )
    c.start()
    await asyncio.sleep(0.05)
    c.stop()
    await asyncio.sleep(0)
    assert json.loads(ws.sent[0]) == {"APIKey": "k"}
    # 비JSON 1건은 격리되고 나머지 2건 전달
    assert got == [{"MessageType": "PositionReport"}, {"a": 1}]
    assert c.status["msg_count"] == 3
    assert c.status["connected"] is False  # stop 후


async def test_reconnect_with_backoff_on_connect_failure():
    attempts = []

    async def connect(url):
        attempts.append(1)
        raise OSError("refused")

    c = StreamCollector("t", "wss://x", lambda m: None,
                        backoff_initial_s=0.01, backoff_max_s=0.02, connect=connect)
    c.start()
    await asyncio.sleep(0.08)
    c.stop()
    assert len(attempts) >= 2
    assert c.status["reconnects"] >= 2
    assert "refused" in (c.status["last_error"] or "")


async def test_resubscribe_sends_on_live_socket():
    ws = FakeWS([])

    async def connect(url):
        return ws

    payloads = iter([{"box": "kr"}, {"box": "taiwan"}])
    c = StreamCollector("t", "wss://x", lambda m: None,
                        subscribe=lambda: next(payloads), connect=connect)
    c.start()
    await asyncio.sleep(0.02)
    c.resubscribe()
    await asyncio.sleep(0.02)
    c.stop()
    assert [json.loads(s) for s in ws.sent] == [{"box": "kr"}, {"box": "taiwan"}]
```

- [ ] **Step 3: 실패 확인**

Run: `uv run --directory hub/backend pytest tests/test_stream.py -v`
Expected: FAIL — `ModuleNotFoundError: labkit.stream`

- [ ] **Step 4: 구현**

`shared/labkit/stream.py`:

```python
"""Persistent WebSocket collector — PollingCollector's streaming sibling.

Reconnects with exponential backoff (backoff_initial_s → backoff_max_s).
Per-message failures are isolated (logged, stream continues); connection
failures are recorded in `status` and retried. `connect` is injectable so
tests never open sockets.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


async def _default_connect(url: str) -> Any:
    import websockets

    return await websockets.connect(url)


class StreamCollector:
    def __init__(
        self,
        name: str,
        url: str,
        on_message: Callable[[dict], None],
        subscribe: Callable[[], dict] | None = None,
        backoff_initial_s: float = 1.0,
        backoff_max_s: float = 60.0,
        connect: Callable[[str], Awaitable[Any]] | None = None,
    ) -> None:
        self.name = name
        self.url = url
        self._on_message = on_message
        self._subscribe = subscribe
        self.backoff_initial_s = backoff_initial_s
        self.backoff_max_s = backoff_max_s
        self._connect = connect or _default_connect
        self._task: asyncio.Task | None = None
        self._ws: Any = None
        self.connected = False
        self.last_msg_at: float | None = None
        self.msg_count = 0
        self.reconnects = 0
        self.last_error: str | None = None

    @property
    def status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "connected": self.connected,
            "last_msg_at": self.last_msg_at,
            "msg_count": self.msg_count,
            "reconnects": self.reconnects,
            "last_error": self.last_error,
        }

    def resubscribe(self) -> None:
        """Re-send the subscription on the live socket (e.g. preset switch).
        No socket → the next (re)connect picks up the new subscribe() value."""
        ws = self._ws
        if ws is not None and self._subscribe is not None:
            asyncio.create_task(self._send_subscribe(ws))

    async def _send_subscribe(self, ws: Any) -> None:
        try:
            assert self._subscribe is not None
            await ws.send(json.dumps(self._subscribe()))
        except Exception as exc:  # 전송 실패 → 수신 루프가 끊김을 감지해 재접속
            logger.warning("[%s] subscribe send failed: %s", self.name, exc)

    async def _run_forever(self) -> None:
        backoff = self.backoff_initial_s
        while True:
            try:
                ws = await self._connect(self.url)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.reconnects += 1
                self.last_error = f"{type(exc).__name__}: {exc}"
                logger.warning("[%s] connect failed: %s", self.name, self.last_error)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self.backoff_max_s)
                continue

            self._ws = ws
            self.connected = True
            backoff = self.backoff_initial_s
            try:
                if self._subscribe is not None:
                    await self._send_subscribe(ws)
                async for raw in ws:
                    self.msg_count += 1
                    self.last_msg_at = time.time()
                    try:
                        self._on_message(json.loads(raw))
                    except Exception:  # 메시지 건별 격리
                        logger.warning("[%s] message handler failed", self.name,
                                       exc_info=True)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                logger.warning("[%s] stream dropped: %s", self.name, self.last_error)
            finally:
                self.connected = False
                self._ws = None
                try:
                    await ws.close()
                except Exception:  # noqa: BLE001 — 이미 죽은 소켓
                    pass
            self.reconnects += 1
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, self.backoff_max_s)

    def start(self) -> asyncio.Task:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(
                self._run_forever(), name=f"stream:{self.name}"
            )
        return self._task

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None
        self.connected = False
        self._ws = None
```

`shared/labkit/__init__.py`에 `from .stream import StreamCollector` + `__all__` 등록.

- [ ] **Step 5: 통과 확인**

Run: `uv run --directory hub/backend pytest tests/test_stream.py -v`
Expected: 3 PASS

- [ ] **Step 6: Commit**

```bash
git add shared/labkit/stream.py shared/labkit/__init__.py shared/pyproject.toml hub/backend/uv.lock hub/backend/tests/test_stream.py
git commit -m "labkit: StreamCollector — WebSocket 상시 수집, 지수 백오프 재접속"
```

---

### Task 4: wake 백엔드 — config·schema·store·정규화

**Files:**
- Create: `hub/backend/app/modules/wake/{__init__.py,config.py,schema.py,store.py,collector.py}`
  (이 태스크에서 `__init__.py`는 빈 파일로만 생성 — 계약 노출은 Task 5)
- Test: `hub/backend/tests/test_wake_normalize.py`

**Interfaces:**
- Consumes: `labkit.TrailStore`, `labkit.config.env_*`
- Produces:
  - `wake.config`: `AIS_URL, AIS_KEY, PRESETS(list[dict{id,label,bbox}]), DEFAULT_PRESET, TRAIL_*, STALE_S, MAX_ENTITIES, ARCHIVE_GAP_S, POSITIONS_RETENTION_DAYS, BRIEF_*` — bbox는 `(lat_min, lon_min, lat_max, lon_max)`
  - `wake.schema`: `DDL: str`, `TABLES: list[str]`, `UPSERT_VESSEL: str`, `INSERT_POSITION: str`
  - `wake.store`: `store: WakeStore` — `.trails: TrailStore`, `.active_preset: str`, `.preset() -> dict`, `.should_archive(eid, ts) -> bool`, `.reset()`
  - `wake.collector`: `normalize_position(msg, now) -> dict | None`, `normalize_static(msg) -> tuple[str, dict] | None`, `ship_type_label(code) -> str`, `handle_message(msg) -> None`, `collector: StreamCollector`

- [ ] **Step 1: 실패하는 테스트 작성**

`hub/backend/tests/test_wake_normalize.py`:

```python
"""AISStream 메시지 정규화 — 비정상 입력 격리, 특수값(511/102.3) 처리."""
from app.modules.wake.collector import (
    normalize_position,
    normalize_static,
    ship_type_label,
)

POSITION_MSG = {
    "MessageType": "PositionReport",
    "MetaData": {"MMSI": 440123456, "ShipName": " HANNARA  ", "time_utc": "..."},
    "Message": {"PositionReport": {
        "Latitude": 35.1, "Longitude": 129.0,
        "Sog": 12.3, "Cog": 245.0, "TrueHeading": 244,
    }},
}


def test_normalize_position():
    p = normalize_position(POSITION_MSG, now=1000.0)
    assert p == {
        "id": "440123456", "ts": 1000.0, "lon": 129.0, "lat": 35.1,
        "sog_kn": 12.3, "cog_deg": 245.0, "heading_deg": 244.0,
        "name": "HANNARA",
    }


def test_normalize_position_unavailable_sentinels():
    msg = {
        "MessageType": "PositionReport",
        "MetaData": {"MMSI": 1},
        "Message": {"PositionReport": {
            "Latitude": 0.0, "Longitude": 0.0,
            "Sog": 102.3, "Cog": 360.0, "TrueHeading": 511,
        }},
    }
    p = normalize_position(msg, now=0.0)
    assert p["sog_kn"] is None and p["cog_deg"] is None and p["heading_deg"] is None
    assert p["name"] is None


def test_normalize_position_rejects_missing_fields():
    assert normalize_position({}, now=0.0) is None
    assert normalize_position({"MetaData": {"MMSI": 1}, "Message": {}}, now=0.0) is None


def test_normalize_static_and_type_label():
    msg = {
        "MessageType": "ShipStaticData",
        "MetaData": {"MMSI": 7},
        "Message": {"ShipStaticData": {
            "Name": "EVER GIVEN ", "Type": 71, "CallSign": "ABCD",
        }},
    }
    mmsi, meta = normalize_static(msg)
    assert mmsi == "7"
    assert meta == {"name": "EVER GIVEN", "ship_type": "화물", "callsign": "ABCD"}
    assert normalize_static({}) is None


def test_ship_type_buckets():
    assert ship_type_label(30) == "어선"
    assert ship_type_label(65) == "여객"
    assert ship_type_label(75) == "화물"
    assert ship_type_label(84) == "탱커"
    assert ship_type_label(0) == "기타"
    assert ship_type_label(None) == "기타"
```

- [ ] **Step 2: 실패 확인**

Run: `uv run --directory hub/backend pytest tests/test_wake_normalize.py -v`
Expected: FAIL — `ModuleNotFoundError: app.modules.wake`

- [ ] **Step 3: config.py 작성**

`hub/backend/app/modules/wake/__init__.py` — 빈 파일 생성 (Task 5에서 채움).
`hub/backend/app/modules/wake/config.py`:

```python
"""Wake module constants (env-overridable via labkit.config helpers)."""
from labkit.config import env_float, env_int, env_str

AIS_URL = env_str("WAKE_AIS_URL", "wss://stream.aisstream.io/v0/stream")
AIS_KEY = env_str("WAKE_AIS_KEY", "")

TRAIL_WINDOW_S = env_float("WAKE_TRAIL_WINDOW_S", 21_600.0)   # 6시간
TRAIL_GAP_S = env_float("WAKE_TRAIL_GAP_S", 60.0)
TRAIL_MIN_MOVE_KM = env_float("WAKE_TRAIL_MIN_MOVE_KM", 0.5)
STALE_S = env_float("WAKE_STALE_S", 3_600.0)                  # 60분 미관측 퇴출
MAX_ENTITIES = env_int("WAKE_MAX_ENTITIES", 5_000)

ARCHIVE_GAP_S = env_float("WAKE_ARCHIVE_GAP_S", 300.0)        # fact 기록 개체당 간격
POSITIONS_RETENTION_DAYS = env_int("WAKE_POSITIONS_RETENTION_DAYS", 7)

BRIEF_MAX_TOKENS = env_int("WAKE_BRIEF_MAX_TOKENS", 700)
BRIEF_BUCKET_S = env_int("WAKE_BRIEF_BUCKET_S", 600)

# 관심 지역 프리셋 — bbox는 (lat_min, lon_min, lat_max, lon_max).
# contrail과 동일 기본 목록 (스펙 §2), 선택 상태는 모듈별 독립.
PRESETS: list[dict] = [
    {"id": "kr", "label": "한반도 주변", "bbox": (30.0, 120.0, 45.0, 135.0)},
    {"id": "taiwan", "label": "대만해협", "bbox": (20.0, 115.0, 28.0, 125.0)},
    {"id": "sea", "label": "동남아", "bbox": (-10.0, 95.0, 15.0, 120.0)},
]
DEFAULT_PRESET = env_str("WAKE_DEFAULT_PRESET", "kr")
```

- [ ] **Step 4: schema.py 작성**

`hub/backend/app/modules/wake/schema.py`:

```python
"""Wake 정규화 스키마 — dim(wake_vessels)은 영구, fact(wake_positions)는 보존기간."""

DDL = """
CREATE TABLE IF NOT EXISTS wake_vessels (
  mmsi TEXT PRIMARY KEY,
  name TEXT,
  ship_type TEXT,
  callsign TEXT,
  first_seen REAL NOT NULL,
  last_seen REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS wake_positions (
  mmsi TEXT NOT NULL,
  ts REAL NOT NULL,
  lon REAL NOT NULL,
  lat REAL NOT NULL,
  sog_kn REAL,
  cog_deg REAL,
  heading_deg REAL,
  PRIMARY KEY (mmsi, ts)
);
CREATE INDEX IF NOT EXISTS idx_wake_positions_ts ON wake_positions (ts);
"""

TABLES = ["wake_vessels", "wake_positions"]

UPSERT_VESSEL = """
INSERT INTO wake_vessels (mmsi, name, ship_type, callsign, first_seen, last_seen)
VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT(mmsi) DO UPDATE SET
  last_seen = excluded.last_seen,
  name      = COALESCE(excluded.name, wake_vessels.name),
  ship_type = COALESCE(excluded.ship_type, wake_vessels.ship_type),
  callsign  = COALESCE(excluded.callsign, wake_vessels.callsign)
"""

INSERT_POSITION = """
INSERT OR IGNORE INTO wake_positions
  (mmsi, ts, lon, lat, sog_kn, cog_deg, heading_deg)
VALUES (?, ?, ?, ?, ?, ?, ?)
"""
```

- [ ] **Step 5: store.py 작성**

`hub/backend/app/modules/wake/store.py`:

```python
"""Wake store: labkit TrailStore + 활성 프리셋 + 아카이브 게이트."""
from __future__ import annotations

from labkit import TrailStore

from . import config


class WakeStore:
    def __init__(self) -> None:
        self.trails = TrailStore(
            window_s=config.TRAIL_WINDOW_S,
            gap_s=config.TRAIL_GAP_S,
            min_move_km=config.TRAIL_MIN_MOVE_KM,
            stale_s=config.STALE_S,
            max_entities=config.MAX_ENTITIES,
        )
        self.active_preset = config.DEFAULT_PRESET
        self._last_archived: dict[str, float] = {}

    def preset(self) -> dict:
        return next(p for p in config.PRESETS if p["id"] == self.active_preset)

    def should_archive(self, eid: str, ts: float) -> bool:
        """fact 기록 게이트: 개체당 ARCHIVE_GAP_S 간격."""
        last = self._last_archived.get(eid)
        if last is not None and ts - last < config.ARCHIVE_GAP_S:
            return False
        self._last_archived[eid] = ts
        if len(self._last_archived) > config.MAX_ENTITIES * 2:  # 게이트 dict 상한
            self._last_archived.clear()
        return True

    def reset(self) -> None:
        """프리셋 전환: trail·게이트 전부 리셋 (아카이브 이력은 유지)."""
        self.trails.reset()
        self._last_archived.clear()


store = WakeStore()
```

- [ ] **Step 6: collector.py 작성**

`hub/backend/app/modules/wake/collector.py`:

```python
"""AISStream collector: labkit StreamCollector + 메시지 정규화.

PositionReport → TrailStore.ingest → (trail 수용분 중 게이트 통과분만) fact 기록.
ShipStaticData → 개체 메타 병합 + dim 갱신. 건별 격리는 StreamCollector가 보장.
"""
from __future__ import annotations

import logging
import time

from labkit import StreamCollector

from ...archive import archive_insert
from . import config, schema
from .store import store

logger = logging.getLogger(__name__)

# AIS ship type code → 대분류 (ITU-R M.1371 2자리 코드)
def ship_type_label(code) -> str:
    try:
        code = int(code)
    except (TypeError, ValueError):
        return "기타"
    if code == 30:
        return "어선"
    if 60 <= code <= 69:
        return "여객"
    if 70 <= code <= 79:
        return "화물"
    if 80 <= code <= 89:
        return "탱커"
    return "기타"


def _clean_name(raw) -> str | None:
    name = str(raw).strip() if raw else ""
    return name or None


def normalize_position(msg: dict, now: float) -> dict | None:
    """AIS 특수값: Sog 102.3 / Cog 360 / TrueHeading 511 = '없음' → None."""
    meta = msg.get("MetaData") or {}
    body = ((msg.get("Message") or {}).get("PositionReport")) or {}
    mmsi = meta.get("MMSI")
    lat, lon = body.get("Latitude"), body.get("Longitude")
    if mmsi is None or lat is None or lon is None:
        return None
    sog, cog, heading = body.get("Sog"), body.get("Cog"), body.get("TrueHeading")
    return {
        "id": str(mmsi),
        "ts": now,
        "lon": float(lon),
        "lat": float(lat),
        "sog_kn": None if sog in (None, 102.3) else float(sog),
        "cog_deg": None if cog in (None, 360.0) else float(cog),
        "heading_deg": None if heading in (None, 511) else float(heading),
        "name": _clean_name(meta.get("ShipName")),
    }


def normalize_static(msg: dict) -> tuple[str, dict] | None:
    meta = msg.get("MetaData") or {}
    body = ((msg.get("Message") or {}).get("ShipStaticData")) or {}
    mmsi = meta.get("MMSI")
    if mmsi is None:
        return None
    return str(mmsi), {
        "name": _clean_name(body.get("Name")),
        "ship_type": ship_type_label(body.get("Type")),
        "callsign": _clean_name(body.get("CallSign")),
    }


def handle_message(msg: dict) -> None:
    mtype = msg.get("MessageType")
    if mtype == "PositionReport":
        point = normalize_position(msg, time.time())
        if point is None:
            return
        added = store.trails.ingest(point)
        if added:  # dim·fact 기록은 trail 수용분만 — 메시지 폭주가 DB에 닿지 않게
            archive_insert(schema.UPSERT_VESSEL, [(
                point["id"], point["name"], None, None, point["ts"], point["ts"],
            )])
            if store.should_archive(point["id"], point["ts"]):
                archive_insert(schema.INSERT_POSITION, [(
                    point["id"], point["ts"], point["lon"], point["lat"],
                    point["sog_kn"], point["cog_deg"], point["heading_deg"],
                )])
    elif mtype == "ShipStaticData":
        parsed = normalize_static(msg)
        if parsed is None:
            return
        mmsi, meta = parsed
        store.trails.merge_meta(mmsi, meta)
        now = time.time()
        archive_insert(schema.UPSERT_VESSEL, [(
            mmsi, meta["name"], meta["ship_type"], meta["callsign"], now, now,
        )])


def _subscribe() -> dict:
    lat_min, lon_min, lat_max, lon_max = store.preset()["bbox"]
    return {
        "APIKey": config.AIS_KEY,
        "BoundingBoxes": [[[lat_min, lon_min], [lat_max, lon_max]]],
        "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
    }


collector = StreamCollector(
    name="wake-ais",
    url=config.AIS_URL,
    on_message=handle_message,
    subscribe=_subscribe,
)
```

- [ ] **Step 7: 통과 확인**

Run: `uv run --directory hub/backend pytest tests/test_wake_normalize.py -v`
Expected: 6 PASS

- [ ] **Step 8: Commit**

```bash
git add hub/backend/app/modules/wake/ hub/backend/tests/test_wake_normalize.py
git commit -m "wake: 백엔드 코어 — AIS 정규화·TrailStore·정규화 스키마"
```

---

### Task 5: wake API·브리핑·모듈 등록

**Files:**
- Create: `hub/backend/app/modules/wake/{api.py,llm.py}`
- Modify: `hub/backend/app/modules/wake/__init__.py` (계약 노출)
- Modify: `hub/backend/app/config.py` (`ALL_MODULES`에 "wake")

**Interfaces:**
- Consumes: Task 4의 `store/collector/config/schema`, Task 2의 `archive_ensure_schema/archive_query/register_prune`, `labkit.BucketCachedText/BedrockError`
- Produces:
  - hub 계약: `META{id:"wake", title:"Wake Watch", icon:"🌊"}, router, startup(), shutdown(), health()`
  - HTTP: `GET /api/wake/region`, `GET|POST /api/wake/preset`, `GET /api/wake/history?id&hours`, `POST /api/wake/brief`, `GET /api/wake/healthz`

- [ ] **Step 1: llm.py 작성**

`hub/backend/app/modules/wake/llm.py`:

```python
"""해상 교통 한국어 브리핑 — quake llm.py 패턴 (10분 버킷 캐시)."""
from __future__ import annotations

from labkit import BucketCachedText

from . import config

_cache = BucketCachedText(config.BRIEF_BUCKET_S)

SYSTEM_PROMPT = (
    "당신은 해상 교통 브리핑 전문가입니다. 주어진 관심 해역의 최근 6시간 선박 "
    "데이터를 바탕으로 반드시 \"지난 6시간, 바다는\"으로 시작하는 한국어 브리핑을 "
    "작성하세요. 구성: (1) 해역 전체 흐름 한 문단, (2) 주목할 선박 2~3척 간단 해설, "
    "(3) 선종 구성의 특징. 과장 없이 담백하게, 수치는 데이터에 있는 것만 사용하세요."
)


def build_user_text(stats: dict, preset_label: str, notable: list[dict]) -> str:
    lines = [
        f"[관심 해역: {preset_label} — 최근 6시간 요약]",
        f"- 관측 선박: {stats['count']}척 (이동 중 {stats['moving']}척)",
        f"- 최다 선종: {stats['top_type'] or 'unknown'}",
        f"- 최고 속력: {stats['max_sog'] or 0}kn",
        "",
        "[속력순 상위 선박]",
    ]
    for v in notable:
        lines.append(
            f"- {v.get('name') or 'MMSI ' + v['id']} | {v.get('ship_type') or '기타'}"
            f" | {v.get('sog_kn') or 0}kn | 침로 {v.get('cog_deg') or '?'}°"
        )
    if not notable:
        lines.append("- (관측 선박 없음 — AIS 키 미설정 또는 수집 초기 상태)")
    return "\n".join(lines)


async def generate_brief(stats: dict, preset_label: str,
                         notable: list[dict]) -> tuple[str, bool, int]:
    """Returns (text, cached, bucket). Raises labkit BedrockError (503/502)."""
    return await _cache.generate(
        key=preset_label,  # 프리셋별 캐시 슬롯
        system=SYSTEM_PROMPT,
        user_text=build_user_text(stats, preset_label, notable),
        max_tokens=config.BRIEF_MAX_TOKENS,
    )
```

- [ ] **Step 2: api.py 작성**

`hub/backend/app/modules/wake/api.py`:

```python
"""Wake API routes — paths relative to the hub's /api/wake prefix."""
from __future__ import annotations

import time
from collections import Counter

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from labkit import BedrockError
from pydantic import BaseModel

from ...archive import archive_query
from . import config, llm
from .collector import collector
from .store import store

router = APIRouter()


def health() -> dict:
    st = collector.status
    if not config.AIS_KEY:
        status = "no_key"
    elif st["connected"]:
        status = "ok"
    else:
        status = "degraded"
    return {
        "status": status,
        "vessels": len(store.trails),
        "preset": store.active_preset,
        "collector": st,
    }


@router.get("/healthz")
async def healthz():
    return health()


def _stats(vessels: list[dict]) -> dict:
    moving = [v for v in vessels if (v.get("sog_kn") or 0) >= 0.5]
    types = Counter((v.get("ship_type") or "기타") for v in vessels)
    return {
        "count": len(vessels),
        "moving": len(moving),
        "top_type": types.most_common(1)[0][0] if types else None,
        "max_sog": max((v.get("sog_kn") or 0 for v in vessels), default=0),
        "last_ingest": store.trails.last_ingest,
    }


@router.get("/region")
async def region():
    store.trails.prune()
    vessels = store.trails.entities()
    return {
        "vessels": vessels,
        "trails": store.trails.trails(),
        "preset": store.active_preset,
        "stats": _stats(vessels),
        "status": "no_key" if not config.AIS_KEY else "ok",
    }


class PresetBody(BaseModel):
    id: str


@router.get("/preset")
async def get_preset():
    return {"presets": config.PRESETS, "active": store.active_preset}


@router.post("/preset")
async def set_preset(body: PresetBody):
    if body.id not in {p["id"] for p in config.PRESETS}:
        raise HTTPException(status_code=422, detail=f"unknown preset: {body.id}")
    if body.id != store.active_preset:
        store.active_preset = body.id
        store.reset()          # 다른 해역의 trail이 섞이지 않게
        collector.resubscribe()  # 라이브 소켓에 새 bbox 구독 재전송
    return {"presets": config.PRESETS, "active": store.active_preset}


@router.get("/history")
async def history(id: str, hours: float = Query(24, gt=0, le=168)):
    cutoff = time.time() - hours * 3600
    rows = archive_query(
        "SELECT ts, lon, lat FROM wake_positions"
        " WHERE mmsi = ? AND ts >= ? ORDER BY ts",
        (id, cutoff),
    )
    return {"id": id, "points": [[r[0], r[1], r[2]] for r in rows]}


@router.post("/brief")
async def brief():
    vessels = store.trails.entities()
    stats = _stats(vessels)
    notable = sorted(vessels, key=lambda v: v.get("sog_kn") or 0, reverse=True)[:10]
    try:
        text, cached, bucket = await llm.generate_brief(
            stats, store.preset()["label"], notable
        )
    except BedrockError as exc:
        if exc.status_code == 503:
            return JSONResponse(status_code=503, content={
                "error": "LLM 토큰이 설정되지 않았습니다",
                "detail": "환경변수 AWS_BEARER_TOKEN_BEDROCK을 설정하면 브리핑을 사용할 수 있습니다.",
            })
        return JSONResponse(status_code=502, content={"error": exc.message})
    return {"brief": text, "cached": cached, "bucket": bucket}
```

- [ ] **Step 3: `__init__.py` 계약 노출**

`hub/backend/app/modules/wake/__init__.py`:

```python
"""Wake Watch — 관심 해역 선박 항적 모니터 (AISStream WebSocket).

Hub module contract: META, router, startup(), shutdown(), health().
"""
import logging

from ...archive import archive_ensure_schema, register_prune
from . import config, schema
from .api import health, router
from .collector import collector

logger = logging.getLogger(__name__)

META = {
    "id": "wake",
    "title": "Wake Watch",
    "tagline": "관심 해역 선박 항적 — AIS 실시간 스트림",
    "icon": "🌊",
}

__all__ = ["META", "router", "startup", "shutdown", "health"]


async def startup() -> None:
    archive_ensure_schema("wake", schema.DDL, schema.TABLES)
    register_prune("wake_positions", "ts", config.POSITIONS_RETENTION_DAYS)
    if config.AIS_KEY:
        collector.start()
    else:
        logger.warning("wake: WAKE_AIS_KEY 미설정 — 수집기 비활성 (health=no_key)")


async def shutdown() -> None:
    collector.stop()
```

- [ ] **Step 4: 모듈 등록**

`hub/backend/app/config.py`의 `ALL_MODULES`를 `["quake", "news", "trend", "market", "contrail", "wake"]`로 변경.
(contrail은 Task 6~7에서 생기지만 main.py가 로드 실패 모듈을 스킵하므로 지금 넣어도 안전 — 단 로그에 경고가 뜨니, 거슬리면 이 단계에서는 "wake"만 추가하고 Task 7에서 "contrail"을 추가해도 된다. **권장: 이 단계에서는 "wake"만 추가.**)

- [ ] **Step 5: curl 검증**

```bash
(cd hub/backend && uv run uvicorn app.main:app --port 8010 &) && sleep 3
curl -s localhost:8010/healthz | python3 -m json.tool          # modules.wake 존재, status no_key(키 없을 때)
curl -s localhost:8010/api/wake/region | python3 -m json.tool  # vessels:[] + status:"no_key"
curl -s localhost:8010/api/wake/preset | python3 -m json.tool  # presets 3개, active kr
curl -s -X POST localhost:8010/api/wake/preset -H 'content-type: application/json' -d '{"id":"taiwan"}'
curl -s -X POST localhost:8010/api/wake/preset -H 'content-type: application/json' -d '{"id":"nope"}' -o /dev/null -w '%{http_code}\n'  # 422
curl -s 'localhost:8010/api/wake/history?id=1' | python3 -m json.tool  # points:[]
kill %1
```

(WAKE_AIS_KEY가 있으면 `WAKE_AIS_KEY=… uv run uvicorn …`으로 띄워 60초 뒤 `/api/wake/region`에 vessels가 채워지는 것,
`sqlite3 hub/backend/data/lab.db "SELECT COUNT(*) FROM wake_positions"`가 증가하는 것까지 확인.)

- [ ] **Step 6: 전체 테스트 + Commit**

Run: `uv run --directory hub/backend pytest tests/ -v` — 전체 PASS 확인.

```bash
git add hub/backend/app/modules/wake/ hub/backend/app/config.py
git commit -m "wake: API·한국어 브리핑·hub 모듈 등록 — Wake Watch 개장"
```

---

### Task 6: contrail 백엔드 — config·auth·정규화·store

**Files:**
- Create: `hub/backend/app/modules/contrail/{__init__.py,config.py,schema.py,store.py,auth.py}`
  (`__init__.py`는 빈 파일 — 계약 노출은 Task 7)
- Test: `hub/backend/tests/test_contrail_normalize.py`

**Interfaces:**
- Consumes: `labkit.TrailStore`, `labkit.config.env_*`, httpx
- Produces:
  - `contrail.config`: `OPENSKY_URL, TOKEN_URL, CLIENT_ID, CLIENT_SECRET, HAS_AUTH, GLOBAL_INTERVAL_S, REGION_INTERVAL_S, FETCH_TIMEOUT_S, PRESETS, DEFAULT_PRESET, TRAIL_*, STALE_S, MAX_ENTITIES, ARCHIVE_GAP_S, POSITIONS_RETENTION_DAYS, BRIEF_*`
  - `contrail.auth`: `async get_token() -> str | None` (실패·미설정 시 None = 익명 폴백)
  - `contrail.schema`: `DDL, TABLES, UPSERT_AIRCRAFT, INSERT_POSITION`
  - `contrail.store`: `store: ContrailStore` — `.trails`, `.active_preset`, `.preset()`, `.should_archive()`, `.reset()`, `.set_global(flights)`, `.global_flights: list[dict]`, `.global_fetch: float | None`
  - `contrail.collector`(Task 7에서 생성하지만 정규화 함수는 여기): `normalize_states(payload: dict, now: float) -> list[dict]` — **이 태스크에서는 `store.py`에 두지 않고 별도 `normalize.py`로 만든다**

- [ ] **Step 1: 실패하는 테스트 작성**

`hub/backend/tests/test_contrail_normalize.py`:

```python
"""OpenSky states 배열 정규화 — 인덱스 계약, 좌표 없는 항목 스킵, 건별 격리."""
from app.modules.contrail.normalize import normalize_states

# states 인덱스: 0 icao24, 1 callsign, 2 origin_country, 3 time_position,
# 4 last_contact, 5 lon, 6 lat, 7 baro_altitude, 8 on_ground, 9 velocity,
# 10 true_track, 11.. 미사용
GOOD = ["abc123", "KAL123 ", "Republic of Korea", 1700000000, 1700000001,
        127.1, 37.5, 10058.4, False, 245.8, 88.2, 0, None, None, None, False, 0]
NO_COORDS = ["dead01", None, "France", None, 1700000001,
             None, None, None, True, None, None, 0, None, None, None, False, 0]
MALFORMED = ["short"]


def test_normalize_good_state():
    out = normalize_states({"states": [GOOD]}, now=1700000010.0)
    assert out == [{
        "id": "abc123", "callsign": "KAL123", "origin_country": "Republic of Korea",
        "ts": 1700000000.0, "lon": 127.1, "lat": 37.5, "alt_m": 10058.4,
        "on_ground": False, "velocity_ms": 245.8, "track_deg": 88.2,
    }]


def test_skips_no_coords_and_malformed_isolated():
    out = normalize_states({"states": [NO_COORDS, MALFORMED, GOOD]}, now=0.0)
    assert len(out) == 1 and out[0]["id"] == "abc123"


def test_ts_falls_back_to_last_contact_then_now():
    s = list(GOOD)
    s[3] = None                      # time_position 없음 → last_contact
    assert normalize_states({"states": [s]}, now=5.0)[0]["ts"] == 1700000001.0
    s[4] = None                      # 둘 다 없음 → now
    assert normalize_states({"states": [s]}, now=5.0)[0]["ts"] == 5.0


def test_empty_payload():
    assert normalize_states({}, now=0.0) == []
    assert normalize_states({"states": None}, now=0.0) == []
```

- [ ] **Step 2: 실패 확인**

Run: `uv run --directory hub/backend pytest tests/test_contrail_normalize.py -v`
Expected: FAIL — `ModuleNotFoundError: app.modules.contrail`

- [ ] **Step 3: config.py 작성**

`hub/backend/app/modules/contrail/__init__.py` — 빈 파일.
`hub/backend/app/modules/contrail/config.py`:

```python
"""Contrail module constants (env-overridable via labkit.config helpers).

무료 한도 예산 (스펙 §2): OAuth 시 전 세계 300s + 지역 60s = 일 ~2,592크레딧
(한도 4,000). 익명 시 900s/300s = 일 ~400크레딧 한도 내.
"""
from labkit.config import env_float, env_int, env_str

OPENSKY_URL = env_str(
    "CONTRAIL_OPENSKY_URL", "https://opensky-network.org/api/states/all"
)
TOKEN_URL = env_str(
    "CONTRAIL_OPENSKY_TOKEN_URL",
    "https://auth.opensky-network.org/auth/realms/opensky-network"
    "/protocol/openid-connect/token",
)
CLIENT_ID = env_str("CONTRAIL_OPENSKY_CLIENT_ID", "")
CLIENT_SECRET = env_str("CONTRAIL_OPENSKY_CLIENT_SECRET", "")
HAS_AUTH = bool(CLIENT_ID and CLIENT_SECRET)

GLOBAL_INTERVAL_S = env_float(
    "CONTRAIL_GLOBAL_INTERVAL_S", 300.0 if HAS_AUTH else 900.0
)
REGION_INTERVAL_S = env_float(
    "CONTRAIL_REGION_INTERVAL_S", 60.0 if HAS_AUTH else 300.0
)
FETCH_TIMEOUT_S = env_float("CONTRAIL_FETCH_TIMEOUT_S", 15.0)

TRAIL_WINDOW_S = env_float("CONTRAIL_TRAIL_WINDOW_S", 21_600.0)  # 6시간
TRAIL_GAP_S = env_float("CONTRAIL_TRAIL_GAP_S", 60.0)
TRAIL_MIN_MOVE_KM = env_float("CONTRAIL_TRAIL_MIN_MOVE_KM", 1.0)  # 항공기는 빠름
STALE_S = env_float("CONTRAIL_STALE_S", 900.0)                    # 15분 미관측 퇴출
MAX_ENTITIES = env_int("CONTRAIL_MAX_ENTITIES", 5_000)

ARCHIVE_GAP_S = env_float("CONTRAIL_ARCHIVE_GAP_S", 300.0)
POSITIONS_RETENTION_DAYS = env_int("CONTRAIL_POSITIONS_RETENTION_DAYS", 7)

BRIEF_MAX_TOKENS = env_int("CONTRAIL_BRIEF_MAX_TOKENS", 700)
BRIEF_BUCKET_S = env_int("CONTRAIL_BRIEF_BUCKET_S", 600)

# 관심 지역 프리셋 — wake와 동일 기본 목록 (bbox = lat_min, lon_min, lat_max, lon_max)
PRESETS: list[dict] = [
    {"id": "kr", "label": "한반도 주변", "bbox": (30.0, 120.0, 45.0, 135.0)},
    {"id": "taiwan", "label": "대만해협", "bbox": (20.0, 115.0, 28.0, 125.0)},
    {"id": "sea", "label": "동남아", "bbox": (-10.0, 95.0, 15.0, 120.0)},
]
DEFAULT_PRESET = env_str("CONTRAIL_DEFAULT_PRESET", "kr")
```

- [ ] **Step 4: normalize.py 작성**

`hub/backend/app/modules/contrail/normalize.py`:

```python
"""OpenSky /states/all 응답 정규화 — 인덱스 기반 states 배열을 dict로."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# states 인덱스 (OpenSky REST API 계약):
# 0 icao24, 1 callsign, 2 origin_country, 3 time_position, 4 last_contact,
# 5 longitude, 6 latitude, 7 baro_altitude(m), 8 on_ground, 9 velocity(m/s),
# 10 true_track(deg)


def normalize_states(payload: dict, now: float) -> list[dict]:
    out: list[dict] = []
    for s in payload.get("states") or []:
        try:
            icao24, lon, lat = s[0], s[5], s[6]
            if not icao24 or lon is None or lat is None:
                continue
            callsign = (s[1] or "").strip()
            out.append({
                "id": str(icao24),
                "callsign": callsign or None,
                "origin_country": s[2],
                "ts": float(s[3] or s[4] or now),
                "lon": float(lon),
                "lat": float(lat),
                "alt_m": None if s[7] is None else float(s[7]),
                "on_ground": bool(s[8]),
                "velocity_ms": None if s[9] is None else float(s[9]),
                "track_deg": None if s[10] is None else float(s[10]),
            })
        except Exception:  # 한 건의 비정상이 나머지를 죽이지 않음
            logger.warning("skipping malformed state entry", exc_info=True)
    return out
```

- [ ] **Step 5: auth.py 작성**

`hub/backend/app/modules/contrail/auth.py`:

```python
"""OpenSky OAuth2 client-credentials 토큰 — 만료 60초 전 갱신, 실패 시 익명 폴백."""
from __future__ import annotations

import logging
import time

import httpx

from . import config

logger = logging.getLogger(__name__)

_token: tuple[float, str] | None = None  # (expires_at, access_token)


async def get_token() -> str | None:
    """자격증명 미설정·발급 실패 → None (호출자는 익명으로 진행)."""
    global _token
    if not config.HAS_AUTH:
        return None
    now = time.time()
    if _token is not None and _token[0] > now + 60:
        return _token[1]
    try:
        async with httpx.AsyncClient(timeout=config.FETCH_TIMEOUT_S) as client:
            resp = await client.post(config.TOKEN_URL, data={
                "grant_type": "client_credentials",
                "client_id": config.CLIENT_ID,
                "client_secret": config.CLIENT_SECRET,
            })
            resp.raise_for_status()
            data = resp.json()
        _token = (now + float(data.get("expires_in", 1800)), data["access_token"])
        return _token[1]
    except Exception as exc:  # noqa: BLE001 — 토큰 실패가 수집을 막지 않는다
        logger.warning("opensky token fetch failed (anonymous fallback): %s", exc)
        return None
```

- [ ] **Step 6: schema.py + store.py 작성**

`hub/backend/app/modules/contrail/schema.py`:

```python
"""Contrail 정규화 스키마 — dim(contrail_aircraft) 영구, fact(contrail_positions) 보존기간."""

DDL = """
CREATE TABLE IF NOT EXISTS contrail_aircraft (
  icao24 TEXT PRIMARY KEY,
  callsign TEXT,
  origin_country TEXT,
  first_seen REAL NOT NULL,
  last_seen REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS contrail_positions (
  icao24 TEXT NOT NULL,
  ts REAL NOT NULL,
  lon REAL NOT NULL,
  lat REAL NOT NULL,
  alt_m REAL,
  velocity_ms REAL,
  track_deg REAL,
  on_ground INTEGER,
  PRIMARY KEY (icao24, ts)
);
CREATE INDEX IF NOT EXISTS idx_contrail_positions_ts ON contrail_positions (ts);
"""

TABLES = ["contrail_aircraft", "contrail_positions"]

UPSERT_AIRCRAFT = """
INSERT INTO contrail_aircraft (icao24, callsign, origin_country, first_seen, last_seen)
VALUES (?, ?, ?, ?, ?)
ON CONFLICT(icao24) DO UPDATE SET
  last_seen      = excluded.last_seen,
  callsign       = COALESCE(excluded.callsign, contrail_aircraft.callsign),
  origin_country = COALESCE(excluded.origin_country, contrail_aircraft.origin_country)
"""

INSERT_POSITION = """
INSERT OR IGNORE INTO contrail_positions
  (icao24, ts, lon, lat, alt_m, velocity_ms, track_deg, on_ground)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""
```

`hub/backend/app/modules/contrail/store.py`:

```python
"""Contrail store: 전 세계 최신 스냅샷 + 관심지역 TrailStore + 아카이브 게이트."""
from __future__ import annotations

import time

from labkit import TrailStore

from . import config


class ContrailStore:
    def __init__(self) -> None:
        self.trails = TrailStore(
            window_s=config.TRAIL_WINDOW_S,
            gap_s=config.TRAIL_GAP_S,
            min_move_km=config.TRAIL_MIN_MOVE_KM,
            stale_s=config.STALE_S,
            max_entities=config.MAX_ENTITIES,
        )
        self.active_preset = config.DEFAULT_PRESET
        self.global_flights: list[dict] = []
        self.global_fetch: float | None = None
        self._last_archived: dict[str, float] = {}

    def preset(self) -> dict:
        return next(p for p in config.PRESETS if p["id"] == self.active_preset)

    def set_global(self, flights: list[dict]) -> None:
        self.global_flights = flights
        self.global_fetch = time.time()

    def should_archive(self, eid: str, ts: float) -> bool:
        last = self._last_archived.get(eid)
        if last is not None and ts - last < config.ARCHIVE_GAP_S:
            return False
        self._last_archived[eid] = ts
        if len(self._last_archived) > config.MAX_ENTITIES * 2:
            self._last_archived.clear()
        return True

    def reset(self) -> None:
        """프리셋 전환: 지역 trail만 리셋 (전 세계 스냅샷은 무관)."""
        self.trails.reset()
        self._last_archived.clear()


store = ContrailStore()
```

- [ ] **Step 7: 통과 확인 + Commit**

Run: `uv run --directory hub/backend pytest tests/test_contrail_normalize.py -v`
Expected: 4 PASS

```bash
git add hub/backend/app/modules/contrail/ hub/backend/tests/test_contrail_normalize.py
git commit -m "contrail: 백엔드 코어 — OpenSky 정규화·OAuth 폴백·정규화 스키마"
```

---

### Task 7: contrail 수집기·API·브리핑·모듈 등록

**Files:**
- Create: `hub/backend/app/modules/contrail/{collector.py,api.py,llm.py}`
- Modify: `hub/backend/app/modules/contrail/__init__.py` (계약 노출)
- Modify: `hub/backend/app/config.py` (`ALL_MODULES`에 "contrail" 추가)

**Interfaces:**
- Consumes: Task 6 전부, Task 2 헬퍼, `labkit.PollingCollector`
- Produces:
  - `collector.py`: `global_collector: PollingCollector("contrail-global")`, `region_collector: PollingCollector("contrail-region")`
  - hub 계약: `META{id:"contrail", title:"Contrail Watch", icon:"✈️"}` 외 4종
  - HTTP: `GET /api/contrail/global`, `GET /api/contrail/region`, `GET|POST /api/contrail/preset`, `GET /api/contrail/history`, `POST /api/contrail/brief`, `GET /api/contrail/healthz`

- [ ] **Step 1: collector.py 작성**

`hub/backend/app/modules/contrail/collector.py`:

```python
"""OpenSky 폴러 2개: 전 세계 스냅샷 + 관심지역 고해상도 (trail·아카이브는 지역만)."""
from __future__ import annotations

import time

import httpx
from labkit import PollingCollector

from ...archive import archive_insert
from . import config, schema
from .auth import get_token
from .normalize import normalize_states
from .store import store


async def _fetch(params: dict | None = None) -> list[dict]:
    token = await get_token()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx.AsyncClient(timeout=config.FETCH_TIMEOUT_S) as client:
        resp = await client.get(config.OPENSKY_URL, params=params, headers=headers)
        resp.raise_for_status()
        payload = resp.json()
    return normalize_states(payload, time.time())


async def fetch_global() -> list[dict]:
    return await _fetch()


async def fetch_region() -> list[dict]:
    lat_min, lon_min, lat_max, lon_max = store.preset()["bbox"]
    return await _fetch({
        "lamin": lat_min, "lomin": lon_min, "lamax": lat_max, "lomax": lon_max,
    })


def _on_global(flights: list[dict]) -> None:
    store.set_global(flights)


def _on_region(flights: list[dict]) -> None:
    dims: list[tuple] = []
    facts: list[tuple] = []
    for f in flights:
        added = store.trails.ingest(f)
        if added:
            dims.append((
                f["id"], f["callsign"], f["origin_country"], f["ts"], f["ts"],
            ))
            if store.should_archive(f["id"], f["ts"]):
                facts.append((
                    f["id"], f["ts"], f["lon"], f["lat"], f["alt_m"],
                    f["velocity_ms"], f["track_deg"], int(f["on_ground"]),
                ))
    # 사이클당 배치 기록 (best-effort — 실패는 로그만)
    archive_insert(schema.UPSERT_AIRCRAFT, dims)
    archive_insert(schema.INSERT_POSITION, facts)
    store.trails.prune()


global_collector = PollingCollector(
    name="contrail-global",
    interval_s=config.GLOBAL_INTERVAL_S,
    fetch=fetch_global,
    on_result=_on_global,
)

region_collector = PollingCollector(
    name="contrail-region",
    interval_s=config.REGION_INTERVAL_S,
    fetch=fetch_region,
    on_result=_on_region,
)
```

- [ ] **Step 2: llm.py 작성**

`hub/backend/app/modules/contrail/llm.py`:

```python
"""항공 교통 한국어 브리핑 — quake llm.py 패턴 (10분 버킷 캐시)."""
from __future__ import annotations

from labkit import BucketCachedText

from . import config

_cache = BucketCachedText(config.BRIEF_BUCKET_S)

SYSTEM_PROMPT = (
    "당신은 항공 교통 브리핑 전문가입니다. 주어진 전 세계·관심지역 최근 6시간 항공 "
    "데이터를 바탕으로 반드시 \"지난 6시간, 하늘은\"으로 시작하는 한국어 브리핑을 "
    "작성하세요. 구성: (1) 전 세계 규모 요약 한 문단, (2) 관심지역 흐름과 주목할 "
    "항공기 2~3대 해설, (3) 특징적인 패턴. 과장 없이 담백하게, 수치는 데이터에 "
    "있는 것만 사용하세요."
)


def build_user_text(global_stats: dict, region_stats: dict,
                    preset_label: str, notable: list[dict]) -> str:
    lines = [
        "[전 세계 스냅샷]",
        f"- 추적 항공기: {global_stats['count']}대 (공중 {global_stats['airborne']}대)",
        f"- 최다 등록 국가: {global_stats['top_country'] or 'unknown'}",
        "",
        f"[관심지역: {preset_label} — 최근 6시간]",
        f"- 관측 항공기: {region_stats['count']}대",
        "",
        "[속도순 상위 항공기]",
    ]
    for f in notable:
        lines.append(
            f"- {f.get('callsign') or f['id']} | {f.get('origin_country') or '?'}"
            f" | 고도 {round((f.get('alt_m') or 0))}m"
            f" | {round((f.get('velocity_ms') or 0) * 3.6)}km/h"
        )
    if not notable:
        lines.append("- (관측 항공기 없음 — 수집 초기 상태)")
    return "\n".join(lines)


async def generate_brief(global_stats: dict, region_stats: dict,
                         preset_label: str, notable: list[dict]) -> tuple[str, bool, int]:
    """Returns (text, cached, bucket). Raises labkit BedrockError (503/502)."""
    return await _cache.generate(
        key=preset_label,
        system=SYSTEM_PROMPT,
        user_text=build_user_text(global_stats, region_stats, preset_label, notable),
        max_tokens=config.BRIEF_MAX_TOKENS,
    )
```

- [ ] **Step 3: api.py 작성**

`hub/backend/app/modules/contrail/api.py`:

```python
"""Contrail API routes — paths relative to the hub's /api/contrail prefix."""
from __future__ import annotations

import asyncio
import time
from collections import Counter

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from labkit import BedrockError
from pydantic import BaseModel

from ...archive import archive_query
from . import config, llm
from .collector import global_collector, region_collector
from .store import store

router = APIRouter()


def health() -> dict:
    failing = (global_collector.consecutive_failures
               + region_collector.consecutive_failures)
    return {
        "status": "ok" if failing == 0 else "degraded",
        "auth": "oauth" if config.HAS_AUTH else "anonymous",
        "global_flights": len(store.global_flights),
        "region_flights": len(store.trails),
        "preset": store.active_preset,
        "collectors": [global_collector.status, region_collector.status],
    }


@router.get("/healthz")
async def healthz():
    return health()


def _global_stats(flights: list[dict]) -> dict:
    airborne = [f for f in flights if not f.get("on_ground")]
    countries = Counter(f.get("origin_country") or "?" for f in flights)
    return {
        "count": len(flights),
        "airborne": len(airborne),
        "top_country": countries.most_common(1)[0][0] if countries else None,
        "last_fetch": store.global_fetch,
    }


def _region_stats(flights: list[dict]) -> dict:
    return {
        "count": len(flights),
        "airborne": len([f for f in flights if not f.get("on_ground")]),
        "last_ingest": store.trails.last_ingest,
    }


@router.get("/global")
async def global_view():
    return {
        "flights": store.global_flights,
        "stats": _global_stats(store.global_flights),
    }


@router.get("/region")
async def region():
    store.trails.prune()
    flights = store.trails.entities()
    return {
        "flights": flights,
        "trails": store.trails.trails(),
        "preset": store.active_preset,
        "stats": _region_stats(flights),
    }


class PresetBody(BaseModel):
    id: str


@router.get("/preset")
async def get_preset():
    return {"presets": config.PRESETS, "active": store.active_preset}


@router.post("/preset")
async def set_preset(body: PresetBody):
    if body.id not in {p["id"] for p in config.PRESETS}:
        raise HTTPException(status_code=422, detail=f"unknown preset: {body.id}")
    if body.id != store.active_preset:
        store.active_preset = body.id
        store.reset()
        # 다음 정규 주기를 기다리지 않고 새 bbox로 즉시 1회 수집
        asyncio.create_task(region_collector.run_once())
    return {"presets": config.PRESETS, "active": store.active_preset}


@router.get("/history")
async def history(id: str, hours: float = Query(24, gt=0, le=168)):
    cutoff = time.time() - hours * 3600
    rows = archive_query(
        "SELECT ts, lon, lat FROM contrail_positions"
        " WHERE icao24 = ? AND ts >= ? ORDER BY ts",
        (id, cutoff),
    )
    return {"id": id, "points": [[r[0], r[1], r[2]] for r in rows]}


@router.post("/brief")
async def brief():
    region_flights = store.trails.entities()
    notable = sorted(
        region_flights, key=lambda f: f.get("velocity_ms") or 0, reverse=True
    )[:10]
    try:
        text, cached, bucket = await llm.generate_brief(
            _global_stats(store.global_flights),
            _region_stats(region_flights),
            store.preset()["label"],
            notable,
        )
    except BedrockError as exc:
        if exc.status_code == 503:
            return JSONResponse(status_code=503, content={
                "error": "LLM 토큰이 설정되지 않았습니다",
                "detail": "환경변수 AWS_BEARER_TOKEN_BEDROCK을 설정하면 브리핑을 사용할 수 있습니다.",
            })
        return JSONResponse(status_code=502, content={"error": exc.message})
    return {"brief": text, "cached": cached, "bucket": bucket}
```

- [ ] **Step 4: `__init__.py` 계약 노출 + 모듈 등록**

`hub/backend/app/modules/contrail/__init__.py`:

```python
"""Contrail Watch — 전 세계 항공 트래픽 + 관심지역 항적 (OpenSky ADS-B).

Hub module contract: META, router, startup(), shutdown(), health().
"""
from ...archive import archive_ensure_schema, register_prune
from . import config, schema
from .api import health, router
from .collector import global_collector, region_collector

META = {
    "id": "contrail",
    "title": "Contrail Watch",
    "tagline": "전 세계 항공 트래픽·관심지역 항적 — OpenSky",
    "icon": "✈️",
}

__all__ = ["META", "router", "startup", "shutdown", "health"]


async def startup() -> None:
    archive_ensure_schema("contrail", schema.DDL, schema.TABLES)
    register_prune("contrail_positions", "ts", config.POSITIONS_RETENTION_DAYS)
    global_collector.start()
    region_collector.start()


async def shutdown() -> None:
    global_collector.stop()
    region_collector.stop()
```

`hub/backend/app/config.py`의 `ALL_MODULES`에 `"contrail"` 추가 →
`["quake", "news", "trend", "market", "contrail", "wake"]`.

- [ ] **Step 5: curl 검증**

```bash
(cd hub/backend && uv run uvicorn app.main:app --port 8010 &) && sleep 8
curl -s localhost:8010/healthz | python3 -m json.tool                    # contrail: auth anonymous, global_flights > 0 (익명 첫 폴 후)
curl -s localhost:8010/api/contrail/global | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["stats"])'
curl -s localhost:8010/api/contrail/region | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["stats"], len(d["trails"]))'
curl -s -X POST localhost:8010/api/contrail/preset -H 'content-type: application/json' -d '{"id":"taiwan"}'
curl -s 'localhost:8010/api/contrail/history?id=nothing' | python3 -m json.tool   # points []
sqlite3 hub/backend/data/lab.db "SELECT COUNT(*) FROM contrail_positions"          # 지역 첫 폴 후 > 0
kill %1
```

주의: 익명 모드 첫 전 세계 폴은 수 초 걸릴 수 있고, OpenSky 익명 크레딧이 소진돼 있으면 429 → health degraded가 정상 동작이다(사이클 격리 확인 기회).

- [ ] **Step 6: 전체 테스트 + Commit**

Run: `uv run --directory hub/backend pytest tests/ -v` — 전체 PASS.

```bash
git add hub/backend/app/modules/contrail/ hub/backend/app/config.py
git commit -m "contrail: 폴러 2계층·API·한국어 브리핑·hub 모듈 등록 — Contrail Watch 개장"
```

---

### Task 8: frontend GeoCanvas 공용 지도 베이스

**Files:**
- Create: `hub/frontend/src/components/continents.ts`
- Create: `hub/frontend/src/components/GeoCanvas.tsx`

**Interfaces:**
- Consumes: `src/apps/quake/QuakeApp.tsx`의 `CONTINENTS` 상수 (복사 원본 — quake 원본은 무변경)
- Produces:
  - `continents.ts`: `export const CONTINENTS: ReadonlyArray<ReadonlyArray<readonly [number, number]>>`
  - `GeoCanvas.tsx`: `WORLD_W=1000, WORLD_H=500`, `project(lon, lat): [number, number]`,
    `type BBox = readonly [number, number, number, number]` (lat_min, lon_min, lat_max, lon_max — 백엔드 프리셋과 동일 순서),
    `bboxViewBox(bbox: BBox | null): string`, `bboxZoomK(bbox: BBox | null): number` (마커 크기 보정용),
    `default GeoCanvas({ bbox, className, children })`

- [ ] **Step 1: continents.ts 생성**

`src/apps/quake/QuakeApp.tsx`의 `const CONTINENTS = […]` 상수(대륙 윤곽 폴리라인 배열, "simple hardcoded continent outlines" 주석 블록 아래 전체)를 그대로 복사해 `hub/frontend/src/components/continents.ts`를 만든다:

```typescript
/* 간이 대륙 윤곽 (lon,lat 폴리라인) — quake 앱의 CONTINENTS를 공용으로 추출한 사본.
   quake 앱은 자체 사본을 유지한다 (이번 작업에서 quake 무변경 원칙). */

export const CONTINENTS: ReadonlyArray<ReadonlyArray<readonly [number, number]>> = [
  // ... QuakeApp.tsx의 배열 전체를 그대로 붙여넣기 ...
];
```

- [ ] **Step 2: GeoCanvas.tsx 작성**

`hub/frontend/src/components/GeoCanvas.tsx`:

```tsx
/* 공용 SVG 지도 베이스 — 등장방형(equirectangular) 투영 + bbox 뷰포트 줌.
   contrail·wake가 공유. 색은 사용하는 앱의 네임스페이스 CSS 변수
   (--map-bg, --land)를 소비한다. */
import type { ReactNode } from "react";
import { CONTINENTS } from "./continents";

export const WORLD_W = 1000;
export const WORLD_H = 500;

/** (lat_min, lon_min, lat_max, lon_max) — 백엔드 프리셋 bbox와 동일 순서 */
export type BBox = readonly [number, number, number, number];

export function project(lon: number, lat: number): [number, number] {
  return [((lon + 180) / 360) * WORLD_W, ((90 - lat) / 180) * WORLD_H];
}

export function bboxViewBox(bbox: BBox | null): string {
  if (!bbox) return `0 0 ${WORLD_W} ${WORLD_H}`;
  const [latMin, lonMin, latMax, lonMax] = bbox;
  const [x1, y1] = project(lonMin, latMax); // 좌상단 = (lon_min, lat_max)
  const [x2, y2] = project(lonMax, latMin);
  return `${x1} ${y1} ${x2 - x1} ${y2 - y1}`;
}

/** 줌 배율 — 마커를 1/k 스케일해 화면상 크기를 일정하게 유지 */
export function bboxZoomK(bbox: BBox | null): number {
  if (!bbox) return 1;
  const [, lonMin, , lonMax] = bbox;
  return 360 / Math.max(1e-6, lonMax - lonMin);
}

export default function GeoCanvas(props: {
  bbox?: BBox | null;
  className?: string;
  children?: ReactNode;
}) {
  const { bbox = null, className, children } = props;
  return (
    <svg
      viewBox={bboxViewBox(bbox)}
      className={className}
      preserveAspectRatio="xMidYMid meet"
      role="img"
    >
      <rect x={0} y={0} width={WORLD_W} height={WORLD_H} className="geo-ocean" />
      {CONTINENTS.map((poly, i) => (
        <polyline
          key={i}
          points={poly.map(([lon, lat]) => project(lon, lat).join(",")).join(" ")}
          className="geo-land"
          vectorEffect="non-scaling-stroke"
        />
      ))}
      {children}
    </svg>
  );
}
```

- [ ] **Step 3: 타입 검증**

Run: `cd hub/frontend && pnpm exec tsc --noEmit`
Expected: 에러 없음 (아직 사용처가 없어도 컴파일 대상).

- [ ] **Step 4: Commit**

```bash
git add hub/frontend/src/components/continents.ts hub/frontend/src/components/GeoCanvas.tsx
git commit -m "frontend: GeoCanvas 공용 지도 베이스 — 등장방형 투영 + bbox 줌"
```

---

### Task 9: Wake Watch 프론트 앱

**Files:**
- Create: `hub/frontend/src/apps/wake/{index.ts,WakeApp.tsx,wake.css}`
- Modify: `hub/frontend/vite.config.ts` (`ALL_APPS`에 "wake"), `hub/frontend/src/App.tsx` (`MENU_ORDER`에 "wake")

**Interfaces:**
- Consumes: Task 8 `GeoCanvas/project/bboxZoomK/BBox`, wake API (`/api/wake/region|preset|history|brief`)
- Produces: `AppDef{id:"wake"}` — 가상 레지스트리 `virtual:apps` 경유로 셸에 노출

- [ ] **Step 1: index.ts 작성**

`hub/frontend/src/apps/wake/index.ts`:

```typescript
import { lazy } from "react";
import type { AppDef } from "../types";

export const app: AppDef = {
  id: "wake",
  title: "Wake Watch",
  tagline: "관심 해역 선박 항적 — AIS 실시간 스트림",
  icon: "🌊",
  Component: lazy(() => import("./WakeApp")),
};
```

- [ ] **Step 2: WakeApp.tsx 작성**

`hub/frontend/src/apps/wake/WakeApp.tsx`:

```tsx
import { useCallback, useEffect, useMemo, useState } from "react";
import "./wake.css";
import GeoCanvas, { project, bboxZoomK, type BBox } from "../../components/GeoCanvas";

const API = "/api/wake";
const REFRESH_MS = 15_000;

/* ---------- API types ---------- */

interface Vessel {
  id: string;
  ts: number;
  lon: number;
  lat: number;
  sog_kn: number | null;
  cog_deg: number | null;
  heading_deg: number | null;
  name?: string | null;
  ship_type?: string | null;
}

interface Trail { id: string; points: [number, number, number][] } // [ts, lon, lat]

interface Preset { id: string; label: string; bbox: BBox }

interface RegionResponse {
  vessels?: Vessel[];
  trails?: Trail[];
  preset?: string;
  status?: string;
  stats?: { count: number; moving: number; top_type: string | null; max_sog: number };
}

const SHIP_TYPES = ["화물", "탱커", "여객", "어선", "기타"] as const;

/** 속력 색: 정박(<0.5kn) 회색 → 20kn+ 주황 */
function speedColor(sog: number | null): string {
  if (sog == null || sog < 0.5) return "var(--muted)";
  const t = Math.min(sog / 20, 1);
  const hue = 210 - t * 180; // 파랑(느림) → 주황(빠름)
  return `hsl(${hue} 80% 55%)`;
}

function VesselMarker(props: { v: Vessel; k: number; selected: boolean; onClick: () => void }) {
  const { v, k, selected, onClick } = props;
  const [x, y] = project(v.lon, v.lat);
  const rot = v.heading_deg ?? v.cog_deg ?? 0;
  const s = 1 / k;
  return (
    <g
      transform={`translate(${x},${y}) rotate(${rot}) scale(${s})`}
      className={`vessel${selected ? " selected" : ""}`}
      onClick={onClick}
    >
      <polygon points="0,-7 4.5,7 -4.5,7" fill={speedColor(v.sog_kn)} />
    </g>
  );
}

export default function WakeApp() {
  const [data, setData] = useState<RegionResponse>({});
  const [presets, setPresets] = useState<Preset[]>([]);
  const [active, setActive] = useState<string>("kr");
  const [typeFilter, setTypeFilter] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [historyPts, setHistoryPts] = useState<[number, number, number][]>([]);
  const [brief, setBrief] = useState<{ text?: string; loading?: boolean; error?: string }>({});

  const load = useCallback(async () => {
    try {
      const r = (await (await fetch(`${API}/region`)).json()) as RegionResponse;
      setData(r);
      if (r.preset) setActive(r.preset);
    } catch { /* 다음 주기 재시도 */ }
  }, []);

  useEffect(() => {
    fetch(`${API}/preset`).then((r) => r.json()).then((p) => {
      setPresets(p.presets ?? []);
      setActive(p.active ?? "kr");
    }).catch(() => {});
    load();
    const t = setInterval(load, REFRESH_MS);
    return () => clearInterval(t);
  }, [load]);

  const switchPreset = useCallback(async (id: string) => {
    setActive(id);
    setSelected(null);
    setHistoryPts([]);
    await fetch(`${API}/preset`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ id }),
    }).catch(() => {});
    load();
  }, [load]);

  const selectVessel = useCallback(async (id: string) => {
    setSelected(id);
    try {
      const h = await (await fetch(`${API}/history?id=${encodeURIComponent(id)}&hours=24`)).json();
      setHistoryPts(h.points ?? []);
    } catch { setHistoryPts([]); }
  }, []);

  const loadBrief = useCallback(async () => {
    setBrief({ loading: true });
    try {
      const r = await fetch(`${API}/brief`, { method: "POST" });
      const b = await r.json();
      setBrief(r.ok ? { text: b.brief } : { error: b.error ?? "브리핑 실패" });
    } catch { setBrief({ error: "브리핑 요청 실패" }); }
  }, []);

  const preset = presets.find((p) => p.id === active) ?? null;
  const bbox = preset?.bbox ?? null;
  const k = bboxZoomK(bbox);

  const vessels = useMemo(() => {
    const all = data.vessels ?? [];
    return typeFilter ? all.filter((v) => (v.ship_type ?? "기타") === typeFilter) : all;
  }, [data.vessels, typeFilter]);
  const shown = new Set(vessels.map((v) => v.id));
  const stats = data.stats;

  return (
    <div className="wrap">
      <header className="head">
        <h1>🌊 Wake Watch</h1>
        <nav className="presets">
          {presets.map((p) => (
            <button
              key={p.id}
              className={p.id === active ? "on" : ""}
              onClick={() => switchPreset(p.id)}
            >{p.label}</button>
          ))}
        </nav>
      </header>

      {data.status === "no_key" && (
        <p className="notice">WAKE_AIS_KEY가 설정되지 않아 수집이 비활성 상태입니다.</p>
      )}

      {stats && (
        <div className="stats">
          <span>선박 <b>{stats.count}</b>척</span>
          <span>이동 중 <b>{stats.moving}</b>척</span>
          <span>최다 선종 <b>{stats.top_type ?? "-"}</b></span>
          <span>최고 속력 <b>{stats.max_sog?.toFixed?.(1) ?? 0}</b>kn</span>
        </div>
      )}

      <div className="chips">
        <button className={!typeFilter ? "on" : ""} onClick={() => setTypeFilter(null)}>전체</button>
        {SHIP_TYPES.map((t) => (
          <button key={t} className={typeFilter === t ? "on" : ""}
                  onClick={() => setTypeFilter(typeFilter === t ? null : t)}>{t}</button>
        ))}
      </div>

      <GeoCanvas bbox={bbox} className="map">
        {(data.trails ?? []).filter((t) => shown.has(t.id)).map((t) => (
          <polyline
            key={t.id}
            points={t.points.map(([, lon, lat]) => project(lon, lat).join(",")).join(" ")}
            className={`trail${t.id === selected ? " selected" : ""}`}
            vectorEffect="non-scaling-stroke"
          />
        ))}
        {selected && historyPts.length > 1 && (
          <polyline
            points={historyPts.map(([, lon, lat]) => project(lon, lat).join(",")).join(" ")}
            className="trail history"
            vectorEffect="non-scaling-stroke"
          />
        )}
        {vessels.map((v) => (
          <VesselMarker key={v.id} v={v} k={k}
                        selected={v.id === selected}
                        onClick={() => selectVessel(v.id)} />
        ))}
      </GeoCanvas>

      <section className="brief">
        <button onClick={loadBrief} disabled={brief.loading}>
          {brief.loading ? "생성 중…" : "🤖 해역 브리핑"}
        </button>
        {brief.text && <p>{brief.text}</p>}
        {brief.error && <p className="error">{brief.error}</p>}
      </section>

      <table className="tbl">
        <thead><tr><th>선명</th><th>MMSI</th><th>선종</th><th>속력</th><th>침로</th></tr></thead>
        <tbody>
          {vessels.slice(0, 50).map((v) => (
            <tr key={v.id} className={v.id === selected ? "on" : ""}
                onClick={() => selectVessel(v.id)}>
              <td>{v.name ?? "-"}</td>
              <td>{v.id}</td>
              <td>{v.ship_type ?? "기타"}</td>
              <td>{v.sog_kn?.toFixed?.(1) ?? "-"}kn</td>
              <td>{v.cog_deg != null ? `${Math.round(v.cog_deg)}°` : "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 3: wake.css 작성**

`hub/frontend/src/apps/wake/wake.css` (quake.css의 네임스페이스 관례 — `.app-wake` 하위, 셸 전역 변수 소비):

```css
/* Wake Watch — 모든 선택자는 .app-wake 하위 네임스페이스.
   테마 의존 색은 셸 전역 변수(--bg/--card/--text/--muted/--border/--accent) 소비. */

.app-wake { --map-bg: #dfeaf2; --land: #9aa7b4; }
[data-theme="dark"] .app-wake { --map-bg: #0a1420; --land: #3d4757; }

.app-wake .wrap { padding: 16px 24px 48px; }
.app-wake .head { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
.app-wake .head h1 { font-size: 20px; margin: 0; }
.app-wake .presets button, .app-wake .chips button {
  border: 1px solid var(--border); background: var(--card); color: var(--text);
  border-radius: 999px; padding: 4px 12px; margin-right: 6px; cursor: pointer;
}
.app-wake .presets button.on, .app-wake .chips button.on {
  border-color: var(--accent); color: var(--accent);
}
.app-wake .notice { color: var(--bad); }
.app-wake .stats { display: flex; gap: 16px; margin: 12px 0; color: var(--muted); }
.app-wake .stats b { color: var(--text); }
.app-wake .chips { margin-bottom: 8px; }
.app-wake .map {
  width: 100%; background: var(--map-bg);
  border: 1px solid var(--border); border-radius: 8px;
}
.app-wake .map .geo-ocean { fill: var(--map-bg); }
.app-wake .map .geo-land { fill: none; stroke: var(--land); stroke-width: 1; }
.app-wake .vessel { cursor: pointer; }
.app-wake .vessel.selected polygon { stroke: var(--accent); stroke-width: 2; }
.app-wake .trail { fill: none; stroke: var(--accent); stroke-width: 1; opacity: .45; }
.app-wake .trail.selected { opacity: 1; stroke-width: 1.5; }
.app-wake .trail.history { stroke-dasharray: 4 3; opacity: .8; }
.app-wake .brief { margin: 16px 0; }
.app-wake .brief button {
  border: 1px solid var(--accent); background: var(--card); color: var(--accent);
  border-radius: 6px; padding: 6px 14px; cursor: pointer;
}
.app-wake .brief p { background: var(--card); border: 1px solid var(--border);
  border-radius: 8px; padding: 12px; box-shadow: var(--shadow); white-space: pre-wrap; }
.app-wake .brief .error { color: var(--bad); }
.app-wake .tbl { width: 100%; border-collapse: collapse; font-size: 13px; }
.app-wake .tbl th, .app-wake .tbl td {
  text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--border);
}
.app-wake .tbl tr { cursor: pointer; }
.app-wake .tbl tr.on td { color: var(--accent); }
```

- [ ] **Step 4: 앱 등록**

- `hub/frontend/vite.config.ts`: `const ALL_APPS = ["quake", "news", "trend", "market", "wake"];`
- `hub/frontend/src/App.tsx`: `const MENU_ORDER = ["market", "news", "trend", "quake", "wake"];`

- [ ] **Step 5: 빌드 + 브라우저 검증**

```bash
cd hub/frontend && pnpm build     # tsc --noEmit + vite build 통과
```

브라우저: `mise run backend:serve` 후 `http://localhost:8000/wake` —
사이드바에 🌊 카드, 지도에 프리셋 bbox 줌, (키 있으면) 마커·트레일, 프리셋 전환, 선박 클릭 → 테이블 하이라이트 + history 점선. 키 없으면 no_key 안내문.

- [ ] **Step 6: Commit**

```bash
git add hub/frontend/src/apps/wake/ hub/frontend/vite.config.ts hub/frontend/src/App.tsx
git commit -m "wake: 프론트 앱 — 해역 지도·속력 마커·트레일·프리셋·브리핑"
```

---

### Task 10: Contrail Watch 프론트 앱

**Files:**
- Create: `hub/frontend/src/apps/contrail/{index.ts,ContrailApp.tsx,contrail.css}`
- Modify: `hub/frontend/vite.config.ts` (`ALL_APPS`에 "contrail"), `hub/frontend/src/App.tsx` (`MENU_ORDER`에 "contrail")

**Interfaces:**
- Consumes: Task 8 GeoCanvas, contrail API (`/api/contrail/global|region|preset|history|brief`)
- Produces: `AppDef{id:"contrail"}`

- [ ] **Step 1: index.ts 작성**

`hub/frontend/src/apps/contrail/index.ts`:

```typescript
import { lazy } from "react";
import type { AppDef } from "../types";

export const app: AppDef = {
  id: "contrail",
  title: "Contrail Watch",
  tagline: "전 세계 항공 트래픽·관심지역 항적 — OpenSky",
  icon: "✈️",
  Component: lazy(() => import("./ContrailApp")),
};
```

- [ ] **Step 2: ContrailApp.tsx 작성**

`hub/frontend/src/apps/contrail/ContrailApp.tsx` — 뷰 2모드: `world`(전 세계 점) / 프리셋(지역 마커+트레일). WakeApp과 같은 골격, 차이만 요약하지 않고 전문을 싣는다:

```tsx
import { useCallback, useEffect, useState } from "react";
import "./contrail.css";
import GeoCanvas, { project, bboxZoomK, type BBox } from "../../components/GeoCanvas";

const API = "/api/contrail";
const WORLD_REFRESH_MS = 60_000;
const REGION_REFRESH_MS = 30_000;

interface Flight {
  id: string;
  ts: number;
  lon: number;
  lat: number;
  callsign?: string | null;
  origin_country?: string | null;
  alt_m: number | null;
  velocity_ms: number | null;
  track_deg: number | null;
  on_ground: boolean;
}

interface Trail { id: string; points: [number, number, number][] }
interface Preset { id: string; label: string; bbox: BBox }

interface GlobalResponse {
  flights?: Flight[];
  stats?: { count: number; airborne: number; top_country: string | null; last_fetch: number | null };
}
interface RegionResponse {
  flights?: Flight[];
  trails?: Trail[];
  preset?: string;
  stats?: { count: number; airborne: number };
}

/** 고도 색: 지상 회색, 저고도 주황 → 순항(10km+) 파랑 */
function altColor(f: Flight): string {
  if (f.on_ground) return "var(--muted)";
  const t = Math.min((f.alt_m ?? 0) / 11_000, 1);
  const hue = 30 + t * 190; // 주황(저고도) → 파랑(순항)
  return `hsl(${hue} 75% 55%)`;
}

export default function ContrailApp() {
  const [view, setView] = useState<string>("world"); // "world" | preset id
  const [presets, setPresets] = useState<Preset[]>([]);
  const [world, setWorld] = useState<GlobalResponse>({});
  const [region, setRegion] = useState<RegionResponse>({});
  const [selected, setSelected] = useState<string | null>(null);
  const [historyPts, setHistoryPts] = useState<[number, number, number][]>([]);
  const [brief, setBrief] = useState<{ text?: string; loading?: boolean; error?: string }>({});

  const loadWorld = useCallback(async () => {
    try { setWorld(await (await fetch(`${API}/global`)).json()); } catch { /* retry next tick */ }
  }, []);
  const loadRegion = useCallback(async () => {
    try { setRegion(await (await fetch(`${API}/region`)).json()); } catch { /* retry next tick */ }
  }, []);

  useEffect(() => {
    fetch(`${API}/preset`).then((r) => r.json()).then((p) => setPresets(p.presets ?? [])).catch(() => {});
  }, []);

  useEffect(() => {
    loadWorld();
    loadRegion();
    const tw = setInterval(loadWorld, WORLD_REFRESH_MS);
    const tr = setInterval(loadRegion, REGION_REFRESH_MS);
    return () => { clearInterval(tw); clearInterval(tr); };
  }, [loadWorld, loadRegion]);

  const switchView = useCallback(async (id: string) => {
    setView(id);
    setSelected(null);
    setHistoryPts([]);
    if (id !== "world") {
      await fetch(`${API}/preset`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ id }),
      }).catch(() => {});
      loadRegion();
    }
  }, [loadRegion]);

  const selectFlight = useCallback(async (id: string) => {
    setSelected(id);
    try {
      const h = await (await fetch(`${API}/history?id=${encodeURIComponent(id)}&hours=24`)).json();
      setHistoryPts(h.points ?? []);
    } catch { setHistoryPts([]); }
  }, []);

  const loadBrief = useCallback(async () => {
    setBrief({ loading: true });
    try {
      const r = await fetch(`${API}/brief`, { method: "POST" });
      const b = await r.json();
      setBrief(r.ok ? { text: b.brief } : { error: b.error ?? "브리핑 실패" });
    } catch { setBrief({ error: "브리핑 요청 실패" }); }
  }, []);

  const isWorld = view === "world";
  const preset = presets.find((p) => p.id === view) ?? null;
  const bbox = preset?.bbox ?? null;
  const k = bboxZoomK(bbox);
  const flights = (isWorld ? world.flights : region.flights) ?? [];
  const gs = world.stats;

  return (
    <div className="wrap">
      <header className="head">
        <h1>✈️ Contrail Watch</h1>
        <nav className="presets">
          <button className={isWorld ? "on" : ""} onClick={() => switchView("world")}>🌍 전 세계</button>
          {presets.map((p) => (
            <button key={p.id} className={view === p.id ? "on" : ""}
                    onClick={() => switchView(p.id)}>{p.label}</button>
          ))}
        </nav>
      </header>

      {gs && (
        <div className="stats">
          <span>추적 <b>{gs.count}</b>대</span>
          <span>공중 <b>{gs.airborne}</b>대</span>
          <span>최다 국가 <b>{gs.top_country ?? "-"}</b></span>
          {!isWorld && region.stats && <span>지역 <b>{region.stats.count}</b>대</span>}
        </div>
      )}

      <GeoCanvas bbox={bbox} className="map">
        {!isWorld && (region.trails ?? []).map((t) => (
          <polyline key={t.id}
            points={t.points.map(([, lon, lat]) => project(lon, lat).join(",")).join(" ")}
            className={`trail${t.id === selected ? " selected" : ""}`}
            vectorEffect="non-scaling-stroke" />
        ))}
        {selected && historyPts.length > 1 && (
          <polyline
            points={historyPts.map(([, lon, lat]) => project(lon, lat).join(",")).join(" ")}
            className="trail history" vectorEffect="non-scaling-stroke" />
        )}
        {isWorld
          ? flights.map((f) => {
              const [x, y] = project(f.lon, f.lat);
              return <circle key={f.id} cx={x} cy={y} r={0.8} fill={altColor(f)} />;
            })
          : flights.map((f) => {
              const [x, y] = project(f.lon, f.lat);
              return (
                <g key={f.id}
                   transform={`translate(${x},${y}) rotate(${f.track_deg ?? 0}) scale(${1 / k})`}
                   className={`plane${f.id === selected ? " selected" : ""}`}
                   onClick={() => selectFlight(f.id)}>
                  <polygon points="0,-7 4.5,7 0,4 -4.5,7" fill={altColor(f)} />
                </g>
              );
            })}
      </GeoCanvas>

      <section className="brief">
        <button onClick={loadBrief} disabled={brief.loading}>
          {brief.loading ? "생성 중…" : "🤖 항공 브리핑"}
        </button>
        {brief.text && <p>{brief.text}</p>}
        {brief.error && <p className="error">{brief.error}</p>}
      </section>

      {!isWorld && (
        <table className="tbl">
          <thead><tr><th>콜사인</th><th>국가</th><th>고도</th><th>속도</th></tr></thead>
          <tbody>
            {flights.slice(0, 50).map((f) => (
              <tr key={f.id} className={f.id === selected ? "on" : ""}
                  onClick={() => selectFlight(f.id)}>
                <td>{f.callsign ?? f.id}</td>
                <td>{f.origin_country ?? "-"}</td>
                <td>{f.alt_m != null ? `${Math.round(f.alt_m)}m` : "-"}</td>
                <td>{f.velocity_ms != null ? `${Math.round(f.velocity_ms * 3.6)}km/h` : "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
```

- [ ] **Step 3: contrail.css 작성**

`hub/frontend/src/apps/contrail/contrail.css` — wake.css와 동일 골격, 네임스페이스만 `.app-contrail`:

```css
/* Contrail Watch — 모든 선택자는 .app-contrail 하위 네임스페이스. */

.app-contrail { --map-bg: #e8eef4; --land: #9aa7b4; }
[data-theme="dark"] .app-contrail { --map-bg: #0b111c; --land: #3d4757; }

.app-contrail .wrap { padding: 16px 24px 48px; }
.app-contrail .head { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
.app-contrail .head h1 { font-size: 20px; margin: 0; }
.app-contrail .presets button {
  border: 1px solid var(--border); background: var(--card); color: var(--text);
  border-radius: 999px; padding: 4px 12px; margin-right: 6px; cursor: pointer;
}
.app-contrail .presets button.on { border-color: var(--accent); color: var(--accent); }
.app-contrail .stats { display: flex; gap: 16px; margin: 12px 0; color: var(--muted); }
.app-contrail .stats b { color: var(--text); }
.app-contrail .map {
  width: 100%; background: var(--map-bg);
  border: 1px solid var(--border); border-radius: 8px;
}
.app-contrail .map .geo-ocean { fill: var(--map-bg); }
.app-contrail .map .geo-land { fill: none; stroke: var(--land); stroke-width: 1; }
.app-contrail .plane { cursor: pointer; }
.app-contrail .plane.selected polygon { stroke: var(--accent); stroke-width: 2; }
.app-contrail .trail { fill: none; stroke: var(--accent); stroke-width: 1; opacity: .45; }
.app-contrail .trail.selected { opacity: 1; stroke-width: 1.5; }
.app-contrail .trail.history { stroke-dasharray: 4 3; opacity: .8; }
.app-contrail .brief { margin: 16px 0; }
.app-contrail .brief button {
  border: 1px solid var(--accent); background: var(--card); color: var(--accent);
  border-radius: 6px; padding: 6px 14px; cursor: pointer;
}
.app-contrail .brief p { background: var(--card); border: 1px solid var(--border);
  border-radius: 8px; padding: 12px; box-shadow: var(--shadow); white-space: pre-wrap; }
.app-contrail .brief .error { color: var(--bad); }
.app-contrail .tbl { width: 100%; border-collapse: collapse; font-size: 13px; }
.app-contrail .tbl th, .app-contrail .tbl td {
  text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--border);
}
.app-contrail .tbl tr { cursor: pointer; }
.app-contrail .tbl tr.on td { color: var(--accent); }
```

- [ ] **Step 4: 앱 등록**

- `vite.config.ts`: `const ALL_APPS = ["quake", "news", "trend", "market", "contrail", "wake"];`
- `App.tsx`: `const MENU_ORDER = ["market", "news", "trend", "quake", "contrail", "wake"];`

- [ ] **Step 5: 빌드 + 브라우저 검증**

```bash
cd hub/frontend && pnpm build
```

브라우저 `http://localhost:8000/contrail`: 🌍 전 세계 뷰에 점 구름(익명 폴 이후), 프리셋 클릭 → 지역 줌 + 기수 방향 마커, 항공기 클릭 → history 점선, 브리핑 버튼(토큰 없으면 503 안내).

- [ ] **Step 6: Commit**

```bash
git add hub/frontend/src/apps/contrail/ hub/frontend/vite.config.ts hub/frontend/src/App.tsx
git commit -m "contrail: 프론트 앱 — 세계/지역 2모드 지도·고도 색 마커·트레일"
```

---

### Task 11: 통합 검증·문서 정리

**Files:**
- Modify: `mise.toml` (frontend:build 설명의 VITE_APPS 예시 갱신)
- Verify only: 전체 스택

**Interfaces:**
- Consumes: Task 1~10 전부
- Produces: 통합 검증 완료 상태 + 최종 커밋

- [ ] **Step 1: mise.toml 설명 갱신**

`[tasks."frontend:build"]`의 description에서 `VITE_APPS=quake,news,trend,market`를
`VITE_APPS=quake,news,trend,market,contrail,wake`로 갱신.

- [ ] **Step 2: 전체 테스트**

Run: `uv run --directory hub/backend pytest tests/ -v`
Expected: Task 1~7의 테스트 전체 PASS (누적 ~19개).

- [ ] **Step 3: 통합 기동 검증**

```bash
mise run build                        # 프론트 빌드 → backend/static/app
(cd hub/backend && uv run uvicorn app.main:app --port 8000 &) && sleep 8
curl -s localhost:8000/healthz | python3 -m json.tool
#   modules에 quake·news·trend·market·contrail·wake 6개, archive 카운트에 contrail/wake 포함
curl -s localhost:8000/api/modules | python3 -m json.tool
#   contrail(✈️)·wake(🌊) 카드 메타 + path
sqlite3 hub/backend/data/lab.db ".tables"
#   contrail_aircraft contrail_positions wake_vessels wake_positions (+기존 entities/snapshots)
sqlite3 hub/backend/data/lab.db "SELECT COUNT(*) FROM contrail_positions"
kill %1
```

브라우저 최종 확인: `/`(홈 카드 6개) → `/contrail` → `/wake` → `/quake`(기존 무손상 회귀 확인).

- [ ] **Step 4: 최종 Commit**

```bash
git add mise.toml
git commit -m "hub: contrail·wake 통합 검증 마무리 — 빌드 설명 갱신"
```

---

## Self-Review 결과 (플랜 작성 시 수행)

- **스펙 커버리지**: 스펙 §1 구조=Task 4~10, §2 소스·예산=Task 4·6, §3 labkit=Task 1~3, §4 스키마=Task 4·6, §5 수집=Task 4·7, §6 API=Task 5·7, §7 화면=Task 8~10, §8 브리핑=Task 5·7, §9 에러=각 태스크 내재, §10 테스트=Task 1~7, §11 순서=태스크 순서 일치. quake 정규화 전환은 스펙 명시대로 범위 밖(후속 스펙).
- **타입 일관성**: `TrailStore.ingest → bool`(Task 1 정의, 4·7 소비), bbox 순서 `(lat_min, lon_min, lat_max, lon_max)`(config·GeoCanvas·AIS 구독 모두 동일), `archive_insert(sql, rows)`(Task 2 정의, 4·7 소비), `BBox`/`project`/`bboxZoomK`(Task 8 정의, 9·10 소비) 확인.
- **플레이스홀더 스캔**: TBD/TODO/"적절히 처리" 없음. 유일한 복사 지시(Task 8 Step 1의
  CONTINENTS)는 저장소 내 정확한 원본 위치를 지정한 것으로 허용.

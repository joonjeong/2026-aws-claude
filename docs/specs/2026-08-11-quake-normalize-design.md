# Quake 아카이브 정규화 전환 설계

- 날짜: 2026-08-11
- 상태: 승인됨
- 선행: contrail+wake 스펙(2026-08-11)의 "후속 작업" 섹션, labkit Archive 정규화 확장(머지 0a63194)

## 목적

quake 모듈의 아카이브 기록을 JSON payload `entities` 테이블에서 정규화 테이블
`quake_events`로 전환한다. 기존 76행은 startup 시 멱등 백필 후 entities에서
삭제한다 (사용자 결정: 단일 진실 공급원).

## 확정된 결정

| 결정 | 선택 | 근거 |
|---|---|---|
| 마이그레이션 방식 | startup() 멱등 자동 실행 | 수동 단계 없음, 재실행 안전, 배포 시 자동 적용 |
| 구 데이터 | 백필 검증 후 entities에서 삭제 | counts() 이중 집계 방지, 정규화 전환의 의도 |
| 테이블 구조 | 단일 quake_events (dim/fact 분리 없음) | 점 이벤트 — 개체/위치 구분이 없음 |
| 보존 정책 | 프루닝 없음 (영구) | 기존 "entities are never pruned" 의미 유지, 소량 |
| 비정상 JSON 행 | 스킵·로그, 삭제하지 않음 | 데이터 손실 방지 — 원본이 유일한 사본 |

## 1. 스키마 (hub/backend/app/modules/quake/schema.py 신설)

```sql
CREATE TABLE IF NOT EXISTS quake_events (
  id       TEXT PRIMARY KEY,
  mag      REAL,
  place    TEXT,
  time     INTEGER,   -- epoch ms (기존 normalize 계약 그대로)
  lon      REAL,
  lat      REAL,
  depth_km REAL
);
CREATE INDEX IF NOT EXISTS idx_quake_events_time ON quake_events (time);
```

- `TABLES = ["quake_events"]`
- `INSERT_EVENT = "INSERT OR IGNORE INTO quake_events (id, mag, place, time, lon, lat, depth_km) VALUES (?, ?, ?, ?, ?, ?, ?)"`
  — INSERT OR IGNORE가 기존 put_entities의 멱등(재관측 무시) 계약을 유지.

## 2. 기록 경로 전환 (collector.py)

`_on_result`의 `archive_entities("quake", [(e["id"], e) for e in events])`를
정규화 기록으로 교체:

```python
archive_insert(schema.INSERT_EVENT, [
    (e["id"], e["mag"], e["place"], e["time"], e["lon"], e["lat"], e["depth_km"])
    for e in events
])
```

normalize()가 모든 키를 보장하므로(비정상은 기본값 대체) 튜플 매핑만으로 충분.
best-effort 계약(archive_insert)은 그대로 — 실패는 로그, 수집은 계속.

## 3. 멱등 마이그레이션 (quake/__init__.py startup(), migrate.py로 분리)

`startup()` 순서:

1. `archive_ensure_schema("quake", schema.DDL, schema.TABLES)`
2. `migrate_entities()` — 신설 `quake/migrate.py`:
   - `archive_query("SELECT id, payload FROM entities WHERE module = 'quake'")`
   - 행별 try/except: `json.loads(payload)` → INSERT_EVENT 튜플. 파싱/키 누락
     행은 경고 로그 후 스킵 — **삭제 대상에서 제외** (원본 보존).
   - 파싱 성공분 일괄 `archive_insert(INSERT_EVENT, rows)`
   - 삭제는 **존재 검증 기반 단일 문장**으로:
     `DELETE FROM entities WHERE module = 'quake' AND id IN (SELECT id FROM quake_events)`
     — INSERT OR IGNORE의 rowcount는 중복 재실행 시 0이라 성공 판정에 쓸 수 없음.
     quake_events에 실재하는 id만 지우므로 INSERT가 통째로 실패한 기동에서는
     아무것도 삭제되지 않고, 이전에 이관됐지만 삭제가 실패했던 행도 재기동 시
     정리된다 (완전 멱등). 실행은 `archive_insert(DELETE_MIGRATED, [()])`
     (인자 없는 executemany 1회) 또는 labkit `query()`가 아닌 실행 경로가
     필요하면 `insert_rows` 재사용 — labkit 변경 없음.
   - 전 과정 best-effort: 어떤 실패도 모듈 기동을 막지 않음. entities에 행이
     남으면 다음 기동에서 재시도 (멱등).
3. `collector.start()` (기존)

- entities에 quake 행이 0건이면 마이그레이션은 즉시 no-op — 매 기동 비용은
  SELECT 1회.

## 4. 에러 처리

- 백필 파싱 건별 격리 (한 행의 비정상이 나머지를 막지 않음).
- INSERT 성공 없이 삭제되는 경로 없음 — DELETE가 quake_events 실재 id에만
  작용하므로 이관 안 된 행은 구조적으로 삭제 불가.
- healthz `archive_counts()`는 변경 불필요 — quake_events는 ensure_schema
  레지스트리로 자동 집계되고, entities의 quake 행은 삭제돼 이중 집계 없음.

## 5. 테스트 (pytest, tmp DB)

- 백필 정상 경로: entities에 JSON 2행 심기 → migrate → quake_events 2행 +
  entities 0행.
- 멱등성: migrate 2회 실행 → 동일 결과.
- 비정상 격리: 깨진 JSON 1행 + 정상 1행 → 정상만 이관·삭제, 비정상은 entities
  잔존.
- 기록 경로: INSERT_EVENT로 저장한 행이 SELECT로 정규화 컬럼 그대로 조회됨.
- 기존 22개 테스트 그린 유지.

## 6. 검증

- pytest 전체.
- 서버 기동 → `sqlite3 lab.db "SELECT COUNT(*) FROM quake_events"` ≥ 76,
  `"SELECT COUNT(*) FROM entities WHERE module='quake'"` = 0,
  `/healthz`의 archive.quake 정상.

## 범위 밖 (YAGNI)

- quake API·store·프론트 변경 (인메모리 경로 무변경)
- labkit 변경 (기존 확장으로 충분)
- news 등 다른 모듈의 entities 정규화 (별도 사이클)
- quake_events 프루닝·보존 정책

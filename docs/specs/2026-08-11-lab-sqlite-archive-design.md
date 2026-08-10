# claude-lab SQLite 이력 아카이브 설계

날짜: 2026-08-11 · 상태: 승인됨

## 목표

폴러가 수집하는 데이터를 append-only SQLite에 쌓아 이력을 남긴다.
인메모리 스토어(labkit stores/TTLCache)는 핫패스로 그대로 유지 — DB는 조회용 아카이브다.

## 결정 사항

- **역할**: 이력 아카이브 (재시작 복원용 아님 — 폴러가 수 초~1분이면 인메모리를 다시 채움)
- **범위**: 4개 모듈 전부 (market·quake·news·trend)
- **파일**: 단일 DB `hub/backend/data/lab.db` (env `LAB_DB_PATH`), WAL + busy_timeout 5s + synchronous=NORMAL
- **동기 sqlite3 그대로 사용**: 쓰기가 사이클당 수 KB라 블로킹 ms 미만, labkit "단일 이벤트 루프" 전제와 일치
- **best-effort 기록**: 아카이브 실패는 로그만 남기고 폴러 사이클·API 응답을 절대 깨지 않는다

## 스키마 (labkit `archive.py`)

```sql
CREATE TABLE entities (          -- 자연 키가 있는 데이터: quake 이벤트, news 기사
  module TEXT, id TEXT, first_seen REAL, payload TEXT,  -- payload = JSON
  PRIMARY KEY (module, id)       -- INSERT OR IGNORE → 폴러 재관측은 no-op
);
CREATE TABLE snapshots (         -- 시계열: market 시세, trend 스냅샷
  module TEXT, kind TEXT, ts REAL, payload TEXT
);
CREATE INDEX idx_snapshots ON snapshots (module, kind, ts);
```

`Archive` API: `put_entities(module, [(id, payload)]) -> new개수` ·
`put_snapshot(module, kind, payload)` · `counts() -> {module: 행수}` ·
`prune_snapshots(days) -> 삭제수` · `close()`

## 구성 지점

| 파일 | 역할 |
|---|---|
| `shared/labkit/archive.py` | Archive 클래스 (재사용 가능한 공용 레이어) |
| `hub/backend/app/archive.py` | env로 인스턴스 생성 + best-effort 헬퍼(`archive_entities`/`archive_snapshot`) + 일일 프루닝 폴러 |
| `quake/collector.py` | `on_result`: store.ingest 후 이벤트 아카이브 (id 키, OR IGNORE가 중복 제거) |
| `news/service.py` | `on_result`: 기사 아카이브 (link 키, source 포함) |
| `trend/collector/youtube.py` | `on_result`: `store.put`이 신규(True)일 때만 스냅샷 아카이브 |
| `market/api/routes.py` | `_cached()`의 상류 fetch 시점, 대시보드 3키(overview/quotes:*)만 — 워밍 폴러든 사용자 요청이든 fetch당 1회 |
| `main.py` | lifespan에서 프루닝 폴러 start/stop, `/healthz`에 `archive` 카운트 노출 |

## 보존 정책

`LAB_ARCHIVE_RETENTION_DAYS` 기본 30, `0`이면 비활성. snapshots만 프루닝
(기동 직후 1회 + 24시간 간격, labkit PollingCollector 재사용).
entities는 증가량이 작아 무제한. 예상 증가량: 하루 ~5MB.

## 에러 처리

- 아카이브 쓰기 실패 → `app/archive.py` 헬퍼가 예외를 삼키고 `log.exception`
- healthz의 카운트 조회 실패 → 빈 dict 폴백
- DB 파일 디렉터리는 기동 시 자동 생성, `hub/backend/data/`는 gitignore

## 테스트

- 스모크: 서버 기동 → 폴러 1사이클 후 `sqlite3 lab.db`로 행 확인, healthz `archive` 카운트 확인
- 재시작 후 카운트가 유지(누적)되는지 확인
- `INSERT OR IGNORE` 멱등성: 두 사이클 후 quake/news 행 수가 이벤트 수 이상으로 늘지 않는지

# Flashpoint Watch — GDELT 분쟁·불안 이벤트 모니터 설계

날짜: 2026-08-11 · 상태: 승인됨 (설계 대화에서 범위·이름·프리셋 확정)

## 1. 목적과 배경

wake(AISStream)가 서비스 장애로 진행 불가한 동안, 사용자 관심사(호르무즈 등
분쟁 해역 정세)를 다른 축으로 충족하는 hub 모듈. 전 세계 뉴스 보도를 기계
코딩한 GDELT v2 이벤트에서 시위~대량폭력(CAMEO 루트 14–20) 이벤트를 상시
수집·정규화·저장하고, 세계지도와 관심지역 확대 뷰로 보여준다.

**한계 명시**: GDELT는 보도 기반 자동 추출이라 중복·오탐·보도 편향이 있다.
화면에 "뉴스 보도 기반 자동 추출 — 검증되지 않은 이벤트 포함" 고지를 상시 노출.

## 2. 데이터 소스 (실측 2026-08-11)

- `http://data.gdeltproject.org/gdeltv2/lastupdate.txt` — 15분마다 최신
  배치 3종 URL 갱신. 이 중 `*.export.CSV.zip`(~65KB)만 사용.
- export 파일: 헤더 없는 탭 구분 61컬럼. 15분당 전체 ~1,000행, 루트 14–20
  필터 + 좌표 보유 ~110행 (일 ~10,500행, 14일 보존 시 ~15만 행 — SQLite 여유).
- 무료·무키. 수시 조회 API(doc 2.0)는 5초/1요청 제한이 있으나 우리는 CSV
  다운로드 경로만 사용 — 15분 폴링과 자연스럽게 일치.

사용 컬럼 (0-기준 인덱스, 실측 검증):
`0 GlobalEventID(PK)` `1 SQLDATE` `6 Actor1Name` `16 Actor2Name`
`26 EventCode` `28 EventRootCode` `29 QuadClass` `30 GoldsteinScale`
`31 NumMentions` `33 NumArticles` `34 AvgTone` `53 ActionGeo_CountryCode`
`56 ActionGeo_Lat` `57 ActionGeo_Long` `59 DATEADDED(YYYYMMDDHHMMSS UTC)`
`60 SOURCEURL`

## 3. 아키텍처 — 상시 수집 → 정규화 → DB → 조회

contrail에서 확정한 원칙 그대로: 화면 전환은 서버 상태를 바꾸지 않는 조회.

- **PollingCollector 1개** (`flashpoint-gdelt`, 기본 900s): lastupdate.txt
  조회 → 직전 처리 URL과 같으면 빈 배치(신규 없음) → 새 URL이면 zip 다운로드
  → 정규화 → `INSERT OR IGNORE` 배치 기록. 재시작 후 같은 파일 재처리는
  event_id PK 멱등으로 흡수. zip·파싱 실패는 사이클 실패로 전파(재시도).
- **인메모리 스토어 없음**: 15분 갱신 데이터라 API가 SQLite를 직접 조회
  (wake/contrail과 다른 점 — 실시간 트레일이 없어 이게 최단 경로).
- 보존: `register_prune("flashpoint_events", "ts", 14일)`.

## 4. 정규화 (normalize.py)

`normalize_export(lines, roots) -> list[dict]`:
- 좌표(56/57) 없는 행 스킵 (~9%), 루트코드(28)가 필터 밖이면 스킵.
- 기형 행은 건별 격리(로그) — 한 행이 배치를 죽이지 않는다.
- ts는 DATEADDED(보도 반영 시각, UTC)를 epoch로. SQLDATE는 이벤트 발생일
  (일 단위)로 별도 보관.
- actor 이름은 공백 정리 후 빈 값 None.

## 5. 스키마 (schema.py) — fact 단일 테이블

```sql
CREATE TABLE IF NOT EXISTS flashpoint_events (
  event_id  INTEGER PRIMARY KEY,   -- GDELT GlobalEventID
  ts        REAL NOT NULL,         -- DATEADDED epoch (보도 반영 시각)
  event_day TEXT,                  -- SQLDATE (이벤트 발생일, YYYYMMDD)
  code      TEXT,                  -- CAMEO 세부코드 (예: 190)
  root      TEXT,                  -- CAMEO 루트 (14~20)
  quad      INTEGER,               -- QuadClass
  goldstein REAL, mentions INTEGER, articles INTEGER, tone REAL,
  actor1 TEXT, actor2 TEXT,
  lat REAL NOT NULL, lon REAL NOT NULL, country TEXT,
  source_url TEXT
);
CREATE INDEX IF NOT EXISTS idx_flashpoint_events_ts ON flashpoint_events (ts);
```

dim 없음 — 이벤트는 일회성 점 이벤트(quake_events 패턴).

## 6. API (prefix /api/flashpoint)

- `GET /events?preset=&hours=24` — hours(0<h≤168), preset 생략 시 전 세계.
  preset은 bbox 서버 필터. 응답: `{events(최신순, 상한 2000), stats, preset}`.
  stats: `{count, by_root, top_country, last_fetch}`.
- `GET /preset` — `{presets, default}`.
- `POST /brief?preset=` — 최근 24h 지역 통계 + 언급 수 상위 이벤트로 한국어
  브리핑 (quake llm 패턴, BucketCachedText 10분, 토큰 없음 503/상류 502).
- `GET /healthz` — collector status + 최근 배치 건수 + DB 행수.

## 7. 프리셋 (config.py)

bbox = (lat_min, lon_min, lat_max, lon_max), 기본 hormuz:

| id | label | bbox |
|---|---|---|
| hormuz | 호르무즈·걸프 | (23, 47, 31, 60) |
| mideast | 중동 | (12, 32, 40, 64) |
| ukraine | 우크라이나 | (44, 22, 53, 41) |
| taiwan | 대만해협 | (20, 115, 28, 125) |

env: `FLASHPOINT_POLL_S=900`, `FLASHPOINT_ROOTS=14,15,16,17,18,19,20`,
`FLASHPOINT_RETENTION_DAYS=14`, `FLASHPOINT_LASTUPDATE_URL`,
`FLASHPOINT_DEFAULT_PRESET=hormuz`, `FLASHPOINT_BRIEF_*` (quake 준용).

## 8. 화면 (FlashpointApp — GeoCanvas 재사용)

- 헤더: ⚡ Flashpoint Watch + 뷰 버튼(🌍 전 세계 | 프리셋 4개).
- 시간 범위 칩: 6h / 24h(기본) / 72h.
- 지도: 마커 색 = 루트 위험도 그라데이션(14 시위 노랑 → 19·20 교전·대량폭력
  빨강), 반지름 = 언급 수(log 스케일, 상한). 클릭 → 테이블 행 하이라이트.
- 테이블(상위 50): 시각 · 유형(한국어 라벨: 14 시위, 15 무력과시, 16 관계축소,
  17 강압, 18 폭행, 19 교전, 20 대량폭력) · 행위자1→행위자2 · 국가 · 출처 링크.
- 통계 바: 이벤트 수 · 최다 유형 · 최다 국가 · 마지막 수집.
- 브리핑 버튼 + 고지 문구(§1).

## 9. 편입 지점

backend `ALL_MODULES`, frontend `vite.config.ts ALL_APPS` + `App.tsx
MENU_ORDER`, `hub/Dockerfile ARG APPS`, `hub_stack.py` apps 허용 목록 —
6곳 모두 `flashpoint` 추가.

## 10. 테스트 계획 (TDD)

- normalize: 정상 행 파싱(컬럼 매핑·ts 변환), 좌표 없음 스킵, 루트 필터,
  기형 행 격리, 빈 페이로드.
- collector: lastupdate.txt 파싱(export URL 선택), 동일 URL 스킵.
- store/api: bbox 필터 정확성(프리셋 경계), hours 검증(422), stats 집계,
  event_id 멱등(INSERT OR IGNORE 재삽입).
- llm: build_user_text에 유형 라벨·상위 이벤트 포함.

## 11. 비범위 (YAGNI)

- 백필(기동 시 과거 파일 소급) — 최신 1파일부터 축적.
- GDELT mentions/gkg 파일, 이벤트 중복 병합(같은 사건 다중 보도), 번역 파이프라인.
- 실시간 스트리밍·웹소켓 — 15분 배치가 소스의 본질.

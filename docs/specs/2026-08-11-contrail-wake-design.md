# Contrail Watch ✈️ + Wake Watch 🌊 — 항공·해상 이동 경로 모니터 설계

- 날짜: 2026-08-11
- 상태: 승인됨
- 선행: quake 모듈 패턴 (docs/specs/2026-08-10-quake-watch-design.md), labkit 공용 레이어

## 목적

hub에 신규 모듈 2개를 추가한다. **contrail**(항공기, OpenSky ADS-B)과
**wake**(선박, AISStream AIS) — 각각 이동 개체의 현재 위치와 **경로(trail)**를
지도에 그리고, 통계 + 한국어 LLM 브리핑을 제공한다. quake가 점 이벤트 모니터라면
이 둘은 이동 개체 모니터다: 개체별 위치 이력이 핵심 자료구조다.

## 확정된 결정

| 결정 | 선택 | 근거 |
|---|---|---|
| 커버리지 | 항공 = 전 세계 스냅샷 + 관심지역 고해상도, 선박 = 관심지역만 | 무료 AIS는 전 세계 REST 스냅샷이 없음 (비대칭 커버리지) |
| 관심 지역 | 서버 프리셋 목록 중 UI 전환 (기본 한반도 주변) | 자유 bbox는 남용·구독 플래핑 리스크, 고정은 유연성 부족 |
| 모듈 구성 | 항공/해상 **모듈 분리** (contrail, wake) | 사용자 선택. 공용 로직은 labkit으로 내려 중복 제거 |
| 네이밍 | contrail(비행운) + wake(항적) | 둘 다 "이동체가 남기는 경로" — 모듈 본질. wake는 quake와 운율 |
| trail 길이 | 최근 6시간, 다운샘플링 필수 | 긴 항로 가시화. 60초 고정 샘플 대신 이동 임계값으로 점 수 억제 |
| LLM 브리핑 | 포함 (quake 패턴 그대로) | 모듈 간 일관성. 10분 버킷 캐시, 503/502 계약 |
| 아카이브 | **정규화 테이블** (dim/fact 분리) | 사용자 지시. 기존 JSON payload 테이블로는 이력 질의 불가 |
| quake 정규화 | 후속 작업으로 명시, 이번 범위 밖 | 사용자 지시 ("이후에 지진도 비슷하게") |

## 1. 구조

```
shared/labkit/
├── stream.py        # 신규: StreamCollector — WebSocket 상시 연결 + 지수 백오프 재접속
├── trails.py        # 신규: TrailStore — 개체별 최신 위치 + 6h 경로, 다운샘플링
└── archive.py       # 확장: ensure_schema / insert_rows / prune_table (정규화 테이블 지원)

hub/backend/app/modules/
├── contrail/        # ✈️ Contrail Watch
│   ├── __init__.py  # META, router, startup(), shutdown(), health() — hub 계약
│   ├── config.py    # 폴링 주기·프리셋·OpenSky 자격증명 (env 오버라이드)
│   ├── collector.py # PollingCollector 2개: 전 세계 + 관심지역
│   ├── store.py     # TrailStore(지역) + 전 세계 최신 스냅샷
│   ├── schema.py    # contrail_aircraft(dim) + contrail_positions(fact) DDL
│   ├── api.py       # /global /region /preset /history /brief
│   └── llm.py       # 한국어 브리핑
└── wake/            # 🌊 Wake Watch — 동일 골격, collector만 StreamCollector

hub/frontend/src/
├── components/GeoCanvas.tsx   # 신규 공용: SVG 지도 베이스 (대륙 윤곽 + bbox 줌)
└── apps/contrail/, apps/wake/ # 앱 2개 (quake 앱 패턴)
```

- hub 모듈 계약(`app/modules/__init__.py`)과 main.py는 무변경.
  `ENABLED_MODULES`에 `contrail`, `wake` 추가만.
- quake 모듈·앱은 이번 작업에서 건드리지 않는다.

## 2. 데이터 소스와 폴링 예산

### OpenSky (contrail)

- `GET https://opensky-network.org/api/states/all` (+`lamin/lamax/lomin/lomax`).
- 무료 계정 OAuth2 client-credentials(일 4,000크레딧) 권장:
  전 세계 300초(288회×4크레딧=1,152) + 지역 60초(1,440회×1크레딧) = 일 2,592크레딧.
- 자격증명 env(`CONTRAIL_OPENSKY_CLIENT_ID/SECRET`) 미설정 시 익명 모드(일 400크레딧)로
  자동 감속: 전 세계 900초, 지역 300초. 주기는 전부 env 오버라이드.
- 토큰 발급 실패·만료 → 익명 폴백, health에 `auth: anonymous|oauth` 노출.

### AISStream (wake)

- `wss://stream.aisstream.io/v0/stream`, 무료 API 키(`WAKE_AIS_KEY`).
- 접속 직후 활성 프리셋 bbox로 구독: MessageTypes = `PositionReport`, `ShipStaticData`.
- 프리셋 전환 시 같은 소켓에 구독 메시지 재전송 (실패 시 재접속으로 폴백).
- 키 미설정: 모듈은 기동하되 health `no_key`, region API는 빈 목록 + `"status":"no_key"`.

### 프리셋

- config 상수 목록 (두 모듈 동일 기본값, 모듈별 env 오버라이드):
  `kr` 한반도 주변(위도 30~45 · 경도 120~135, 기본), `taiwan` 대만해협, `sea` 동남아.
- 활성 프리셋은 모듈별 독립 인메모리 상태 (재시작 시 기본값 복귀 — 영속화 안 함).

## 3. labkit 확장

### StreamCollector (stream.py)

- `StreamCollector(name, url, on_message, subscribe=None)` — asyncio 태스크로
  WebSocket 상시 연결. `start()/stop()`은 PollingCollector와 동일 시그니처.
- 연결 성공 시 `subscribe()` 콜러블이 주는 페이로드 전송. `resubscribe()` 호출 시
  현재 소켓에 재전송, 소켓 없으면 다음 연결에서 반영.
- 끊김·오류 → 지수 백오프 1초→60초 상한 재접속. 메시지 콜백 예외는 건별 격리(로그).
- `status()` → `{connected, last_msg_at, msg_count, reconnects}`.
- 의존성: `websockets` 패키지 추가 (backend pyproject).

### TrailStore (trails.py)

- `dict[id → {latest: dict, trail: deque[(ts, lon, lat)]}]`.
- `ingest(point)`: `latest`는 항상 갱신. trail 점 추가는
  **마지막 점 대비 gap_s(기본 60초) 경과 AND min_move_km(기본 0.5) 이상 이동** 시에만
  — 정박·주기장 개체는 점 1개로 유지된다. 추가된 점은 반환해 호출자(아카이브)가 쓴다.
- 프루닝: 유입 시 6시간(`window_s`) 지난 점 제거. `stale_s` 동안 미관측 개체 퇴출
  (contrail 900초, wake 3,600초). `max_entities`(기본 5,000) 초과 시 오래된 것부터.
- `reset()`: 프리셋 전환 시 전체 비움. 단일 이벤트 루프 전제, 락 없음 (stores.py 관례).

### Archive 정규화 확장 (archive.py)

- `ensure_schema(module, ddl, tables)`: 모듈 DDL 실행 + `{table→module}` 레지스트리
  등록 (counts()가 정규화 테이블도 모듈별 집계).
- `insert_rows(sql, rows)`: executemany + commit 래퍼.
- `prune_table(table, ts_col, days)`: fact 테이블 보존기간 삭제.
- 기존 `entities`/`snapshots`와 기존 모듈 경로는 무변경. hub의 best-effort 헬퍼
  (`app/archive.py`) 관례를 따르는 모듈별 래퍼로만 호출.

## 4. 정규화 스키마 (schema.py)

```sql
-- contrail: dim은 영구, fact는 보존기간 프루닝
CREATE TABLE IF NOT EXISTS contrail_aircraft (
  icao24 TEXT PRIMARY KEY, callsign TEXT, origin_country TEXT,
  first_seen REAL NOT NULL, last_seen REAL NOT NULL);
CREATE TABLE IF NOT EXISTS contrail_positions (
  icao24 TEXT NOT NULL, ts REAL NOT NULL, lon REAL NOT NULL, lat REAL NOT NULL,
  alt_m REAL, velocity_ms REAL, track_deg REAL, on_ground INTEGER,
  PRIMARY KEY (icao24, ts));
CREATE INDEX IF NOT EXISTS idx_contrail_positions_ts ON contrail_positions (ts);

-- wake: 동일 골격
CREATE TABLE IF NOT EXISTS wake_vessels (
  mmsi TEXT PRIMARY KEY, name TEXT, ship_type TEXT, callsign TEXT,
  first_seen REAL NOT NULL, last_seen REAL NOT NULL);
CREATE TABLE IF NOT EXISTS wake_positions (
  mmsi TEXT NOT NULL, ts REAL NOT NULL, lon REAL NOT NULL, lat REAL NOT NULL,
  sog_kn REAL, cog_deg REAL, heading_deg REAL,
  PRIMARY KEY (mmsi, ts));
CREATE INDEX IF NOT EXISTS idx_wake_positions_ts ON wake_positions (ts);
```

- dim 갱신: 관측마다 `INSERT … ON CONFLICT DO UPDATE last_seen` (+정적정보 채움).
- fact 기록: **관심지역 + TrailStore가 수용한 점** 중 개체당 `*_ARCHIVE_GAP_S`
  (기본 300초) 간격만. 전 세계 스냅샷은 기록하지 않는다 — 폭주 차단.
  예상 규모 일 ~10만 행 이내.
- fact 보존: `*_POSITIONS_RETENTION_DAYS` 기본 7일 — 기존 24시간 프루닝 폴러
  (`app/archive.py`의 prune_poller)에 `prune_table` 호출 편입.

## 5. 수집·정규화

### contrail (collector.py)

- PollingCollector 2개: `contrail-global`(전 세계), `contrail-region`(활성 프리셋 bbox).
- OpenSky states 배열 정규화 (인덱스 기반):
  `icao24, callsign(strip), origin_country, time_position→ts, lon, lat,
  baro_altitude→alt_m, velocity→velocity_ms, true_track→track_deg, on_ground`.
  좌표 없는 항목(lon/lat null)은 스킵. 건별 try/except 격리 (quake normalize 관례).
- global 결과 → 스냅샷 스토어(최신 목록 교체). region 결과 → TrailStore.ingest
  → 수용된 점을 dim/fact 아카이브 (best-effort).

### wake (collector.py)

- StreamCollector 1개. `PositionReport` → `{mmsi, ts, lon, lat, sog_kn, cog_deg,
  heading_deg}` → TrailStore.ingest → 아카이브. `ShipStaticData` → 선명·종류·콜사인을
  개체 메타에 병합 + dim 갱신. ship_type 숫자 코드는 대분류 문자열로 매핑
  (화물/탱커/여객/어선/기타).
- 메시지 폭주는 TrailStore 다운샘플링이 흡수 — `latest`만 매번 갱신되고
  trail·아카이브는 임계값 통과분만.

## 6. API 계약 (api.py)

| 엔드포인트 | 응답 |
|---|---|
| `GET /api/contrail/global` | `{"flights":[…latest], "stats":{count, airborne, top_country, last_fetch}}` |
| `GET /api/contrail/region` | `{"flights":[…], "trails":[{id, points:[[ts,lon,lat]…]}], "preset", "stats"}` |
| `GET /api/wake/region` | `{"vessels":[…], "trails":[…], "preset", "stats":{count, top_type, max_sog}, "status"}` |
| `GET /api/{id}/preset` | `{"presets":[{id,label,bbox}…], "active":"kr"}` |
| `POST /api/{id}/preset` | `{"id":"taiwan"}` → 전환. wake는 AIS 재구독 + TrailStore reset. 미지 id → 422 |
| `GET /api/{id}/history?id=…&hours=24` | 정규화 fact 질의 — 6h 인메모리 창 너머 항적 `{"points":[…]}` |
| `POST /api/{id}/brief` | `{"brief","cached","bucket"}` — quake 계약 동일 |

- health(): 수집기 status + 개체 수 + 활성 프리셋 (+wake는 `no_key` 여부).

## 7. 화면 (apps/contrail, apps/wake)

- **GeoCanvas.tsx** (공용): quake 앱의 SVG 대륙 윤곽 + 등장방형 변환을 추출,
  bbox 뷰포트 줌 추가. quake 앱은 이번엔 미변경 (후속에 옮겨탈 수 있음).
- **Contrail**: 통계 바(총 대수·공중·최다 국가·마지막 수집) / 세계 뷰 점 →
  프리셋 선택 시 지역 뷰 — 기수 방향 삼각 마커 + 트레일 폴리라인,
  색 = 고도(지상 회색→저고도 주황→순항 파랑) / 테이블(콜사인·국가·고도·속도) /
  개체 클릭 → history 오버레이. 갱신: 세계 60초, 지역 30초.
- **Wake**: 지역 뷰 전용 — 침로 삼각 마커, 색 = 속력(정박 회색→고속 주황),
  종류 필터 칩, 테이블(선명·MMSI·종류·속력), 클릭 → history 오버레이. 갱신 15초.
- 테마·레이아웃: 기존 셸 CSS 변수. 런처 카드: `✈️ Contrail Watch — 전 세계 항공
  트래픽·관심지역 항적`, `🌊 Wake Watch — 관심 해역 선박 항적 (AIS 실시간)`.

## 8. 브리핑 (llm.py)

- quake llm.py 패턴 복제: Bedrock converse REST 직접 호출, `maxTokens 700`,
  10분 버킷 캐시, 토큰 미설정 503 / 업스트림 오류 502.
- 입력: 6시간 통계 + 주목 개체(최고속·최고고도·최장 트레일 등 상위 10).
- 시작 문구: contrail "지난 6시간, 하늘은" / wake "지난 6시간, 바다는".

## 9. 에러 처리 요약

- 폴링 사이클·스트림 메시지·정규화 건별·아카이브 — 전부 격리 (실패는 로그, 흐름 유지).
- OpenSky 429/비200: 로그 후 다음 주기. 자격증명 없음 → 감속 모드.
- AIS 키 없음: health `no_key` + 빈 응답. 브리핑: 데이터 없으면 상황 설명 프롬프트.
- 키의 거처: `CONTRAIL_OPENSKY_CLIENT_ID/SECRET`, `WAKE_AIS_KEY`,
  `AWS_BEARER_TOKEN_BEDROCK` — 환경변수로만. 코드·리포지토리에 없음.

## 10. 테스트와 검증

- pytest (순수 로직): TrailStore 다운샘플·6h 프루닝·상한 퇴출·reset,
  OpenSky/AIS 정규화(비정상 입력 격리), Archive ensure_schema/insert/prune.
- API: curl — `/global`, `/region`, `/preset` 전환, `/history`, `/brief` 캐시 2회.
- 화면: 브라우저 확인 (마커 방향·트레일·프리셋 전환·필터).

## 11. 구현 순서

| Phase | 내용 | 검증 |
|---|---|---|
| 1 | labkit: trails.py + stream.py + archive 확장 | pytest |
| 2 | wake 백엔드 (수집→store→아카이브→API) | curl + sqlite3로 정규화 행 확인 |
| 3 | contrail 백엔드 | curl (익명 모드 폴백 포함) |
| 4 | GeoCanvas + wake 앱 + contrail 앱 | 브라우저 |
| 5 | 브리핑 2개 | curl 2회 — 두 번째 `cached:true` |
| 6 | 셸 카드·ENABLED_MODULES 등록 | /healthz, /api/modules |

## 후속 작업 (이번 범위 밖, 사용자 지시로 명시)

- **quake 정규화 전환**: `quake_events(id PK, mag REAL, place TEXT, time INTEGER,
  lon REAL, lat REAL, depth_km REAL)` 신설 → 기존 `entities` JSON payload 백필
  마이그레이션 → collector 기록 경로 전환. 별도 스펙·사이클로 진행.
- market/news/trend 정규화도 같은 패턴으로 검토 가능.

## 범위 밖 (YAGNI)

- 실시간 푸시(SSE/WebSocket→클라이언트) — 폴링으로 충분
- 자유 bbox 지정, 프리셋 영속화
- 항로 예측·근접 경보·지오펜스
- 기체/선박 외부 DB(사진·제원) 연동
- CDK 변경 — 단일 컨테이너에 모듈 추가일 뿐, 기존 스택 그대로

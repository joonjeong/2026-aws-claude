# 데이터레이크 설계 — shared/datalake

날짜: 2026-08-11 · 상태: 초안(사용자 리뷰 대기)

## 1. 배경과 목표

hub는 6개 모듈(quake·news·trend·market·contrail·wake)이 외부 소스를 수집해
인메모리 스토어로 서빙하고, 정규화된 일부만 SQLite 아카이브(`lab.db`)에 남긴다.
**원본(raw) 페이로드는 어디에도 보존되지 않으며**, 정규화에서 버려진 필드는
소실되고, fact 테이블은 7~30일 프루닝된다. 배포 환경(Fargate)에서는 `lab.db`
자체가 태스크 재시작 시 사라진다.

목표: 동일한 소스를 **hub와 완전히 독립적으로** 수집해 원본을 디렉토리 기반
레이크에 append-only로 적재하고, 옵션으로 정규화본을 자체 SQLite에 저장한다.
각 소스는 재사용 가능한 코어 클라이언트로 만들어 향후 통합 마켓 영향도
모니터링 솔루션이 import해 조합할 수 있게 한다.

**핵심 제약 (사용자 지정):**
1. hub 웹서비스에 어떤 영향도 주지 않는 독립 코드 (별도 프로세스, `lab.db` 접근 금지)
2. 수집 주기는 hub와 동일
3. 작업 경로 `shared/datalake`, 디렉토리 저장 기본 + SQLite 옵션
4. 소스별 재사용 가능한 코어 클라이언트

## 2. 데이터 인벤토리 (현황)

| 모듈 | 소스 | 인증 | hub 수집 주기 | 원본 형태 | 정규화 산출물 | hub 저장 |
|---|---|---|---|---|---|---|
| quake | USGS `2.5_day.geojson` | 없음 | 60s (`QUAKE_POLL_INTERVAL_S`) | GeoJSON FeatureCollection | `{id, mag, place, time, lon, lat, depth_km}` | `quake_events` (영구) |
| news | RSS 15개 매체 (BBC·Guardian·NHK·연합·AlJazeera·한겨레·경향·조선·SBS·매경·한경·NPR·NYT·Fox·WaPo) | 없음 (UA 오버라이드) | 소스당 120s (`NEWSROOM_POLL_INTERVAL_S`) | RSS 2.0 XML | `{source, title, link, published, summary}` (HTML 제거, 최신 15건) | `news_articles` (영구) |
| trend | YouTube Data API v3 `videos?chart=mostPopular&regionCode=KR` | `YT_API_KEY` | 60s (`POLL_INTERVAL_S`) | JSON items ≤30 | `{video_id, title, channel, category_id, thumbnail, view_count, like_count, published_at}` | `trend_videos`(dim) + `trend_video_stats`(fact, 30일) |
| market | yfinance(미) · pykrx(한) · Yahoo RSS(종목뉴스) · 시뮬레이션(호가/수급) | 없음 | 워밍 30s + 장중 TTL 45s / 장외 600s — `overview`, `quotes:us`, `quotes:kr` 3키만 아카이브 | pandas DataFrame → dict | 시세 행 `{symbol, name, price, change, change_pct, volume}`, overview `{indices, indicators}` | `snapshots` JSON (30일) |
| contrail | adsb.lol re-api (기본, 무인증) / OpenSky(롤백 경로) | 없음 / OAuth2 | 전세계 600s + 프리셋 4개 병렬 60s (`CONTRAIL_GLOBAL/REGION_INTERVAL_S`) | readsb v2 `{"ac":[...]}` | `{id, callsign, ts, lon, lat, alt_m, on_ground, velocity_ms, track_deg, ...}` | `contrail_aircraft`(dim) + `contrail_positions`(fact, 7일, 개체당 300s 게이트) |
| wake | AISStream WebSocket | `WAKE_AIS_KEY` (구독 프레임) | 상시 스트림 (폴링 아님) | AIS `PositionReport`/`ShipStaticData` JSON | `{id(MMSI), ts, lon, lat, sog_kn, cog_deg, heading_deg, name}` + 선박 dim | `wake_vessels`(dim) + `wake_positions`(fact, 7일, 트레일 게이트) |
| flashpoint | GDELT v2 15분 export CSV (`lastupdate.txt` → `.export.CSV.zip`) | 없음 | 900s (`FLASHPOINT_POLL_S`), 같은 파일 재등장은 빈 배치 | 헤더 없는 탭 구분 61컬럼 CSV | CAMEO 루트 14~20 필터 + `{event_id, ts, code, root, quad, goldstein, mentions, articles, tone, actor1/2, lat, lon, country, source_url}` | `flashpoint_events` (14일) |

LLM 파생물(브리핑·렌즈·AI 분석)은 전 모듈에서 버킷 캐시로만 존재하고 어디에도
저장되지 않는다. 데이터레이크 1차 범위는 **외부 소스 원본**이며 LLM 파생물
적재는 범위 외(향후 확장 후보).

## 3. 접근 방식 결정

| 방식 | 내용 | 판정 |
|---|---|---|
| A. 독립 패키지 + labkit 재사용 | 검증된 labkit(폴러·스트림·env·Archive)만 라이브러리로 재사용 | v0.1 채택 → **v0.2에서 폐기** |
| B. hub 모듈 collector import | hub 코드 직접 재사용 | 기각 — hub `app.*` config/전역 상태에 결합, 독립성 제약 위반 |
| C. 완전 무의존 | labkit도 안 쓰고 자체 구현 | **v0.2 채택** (사용자 결정 2026-08-11) |

**v0.2 결정 변경 (2026-08-11, 사용자 지시):**
1. labkit 결합 제거 — 의존성은 httpx·feedparser·websockets뿐. 스트림 수집기·
   env 헬퍼·SQLite 래퍼는 `datalake/core/`에 자체 구현.
2. 실행 모델을 **소스별 one-shot CLI**로 전환 — 클라이언트를 래핑하는
   `uv run datalake-<source>` 명령이 1회 수집→적재 후 종료.
3. **스케줄링 기능 전면 제거** — 상시 폴링 루프(Runner/PollingCollector),
   market 장시간 TTL 게이트, 일일 유지보수 폴러는 향후 도입할 Temporal 등
   외부 오케스트레이터와 중복이므로 삭제. 주기는 §6의 권장 스케줄 문서로만
   유지하고, 실패는 종료 코드(0/1/2)로 전달해 재시도를 오케스트레이터에 맡긴다.

## 4. 아키텍처

```
shared/datalake/
├── pyproject.toml            # deps: httpx, feedparser, websockets (labkit 없음)
│                             # [project.scripts] datalake-* 명령 9개
├── datalake/
│   ├── config.py             # DATALAKE_* env
│   ├── core/
│   │   ├── source.py         # Record (스케줄 메타 없음)
│   │   ├── env.py            # env_str/int/float (자체 구현)
│   │   ├── stream.py         # StreamCollector — 백오프 재접속, connect 주입
│   │   ├── sinks.py          # FileSink(기본)
│   │   ├── transform.py      # Record → 정규화 테이블 행 (model.py 스펙과 짝)
│   │   ├── parquet.py        # raw 순회 + Parquet 파티션 물질화(materialize)
│   │   └── maintenance.py    # gzip 로테이션·보존 프루닝 (one-shot 함수)
│   ├── sources/              # ★ 순수 코어 클라이언트 (모듈당 1파일)
│   │   ├── quake.py news.py trend.py contrail.py wake.py market.py flashpoint.py
│   ├── cli/                  # ★ 소스별 one-shot CLI (클라이언트 래핑)
│   │   ├── _common.py        #   싱크 조립·배출 격리·run_async(종료 코드)
│   │   ├── quake.py … flashpoint.py, normalize.py, maintenance.py
│   └── model.py              # ★ 정규화 존 데이터 모델 단일 진실 (pyarrow 스키마)
└── tests/
```

**코어 클라이언트 계약** — 각 `sources/<id>.py`는:
- `class <Id>Client` — `fetch*() -> list[Record]` (poll) 또는
  `subscribe_payload()/parse(msg)` (stream). 원본 페이로드를 그대로 반환.
- `normalize(payload) -> rows` — hub와 동일한 정규화 (SQLite 싱크·후속 소비자용)
- `build() -> Client | None` — None = 키·엑스트라 부재로 비활성
- 저장·경로·DB·스케줄을 일절 모름 → 어떤 소비자든 그대로 import 가능

**CLI 계약** — `uv run datalake-<source>`:
- 1회 수집→전 싱크 배출→종료. 종료 코드 0 성공 / 1 실패 / 2 소스 비활성
- 재시도·백오프 없음 (오케스트레이터 소유). wake만 `--duration`으로 구간 실행

**독립성 보장:**
- `hub.*` / `app.*` / `labkit` import 금지 (테스트로 강제: import 그래프 검사)
- 자체 데이터 루트 `DATALAKE_ROOT` (기본 `shared/datalake/data/`, gitignore)
- `lab.db` 경로를 알지도 못함. SQLite 옵션은 자체 `datalake.db`
- 별도 프로세스, 향후 Temporal 액티비티/컨테이너로 그대로 이식 가능

## 5. 저장 설계

### 5.1 디렉토리 레이크 (기본, 항상 켜짐)

Hive 스타일 파티션 + JSONL — 나중에 DuckDB/Athena/pandas로 바로 읽힌다:

```
<DATALAKE_ROOT>/raw/<source>/<kind>/dt=YYYY-MM-DD/part-HH.jsonl
```

한 줄 = 봉투(envelope) 하나:

```json
{"fetched_at": "2026-08-11T06:00:00Z", "source": "quake", "kind": "usgs_feed",
 "meta": {"url": "...", "status": 200, "elapsed_ms": 312}, "payload": { ...원본 그대로... }}
```

- 폴링 소스: 사이클당 1행 (원본 응답 전체). news는 매체당 1행.
- wake 스트림: 메시지를 버퍼에 모아 `DATALAKE_FLUSH_S`(기본 10s)마다 플러시.
- append-only, 시간 단위 파일 로테이션. 쓰기 실패는 로그만 남기고 수집 계속
  (hub 아카이브와 동일한 best-effort 계약).
- 용량 추정: contrail 전세계 스냅샷(~2MB×144회/일)이 지배적 — 일 300~400MB.
  `DATALAKE_COMPRESS=1`(기본 켜짐)이면 전일 파티션을 gzip 압축(약 1/10).
  `DATALAKE_RAW_RETENTION_DAYS`(기본 0=무제한)로 프루닝 옵션.

### 5.2 Parquet 정규화 존 (v0.3 — SQLite 대체, 사용자 결정 2026-08-11)

- v0.1~0.2의 SQLite 파생 존은 제거. **DB 없음 — 파일이 인터페이스**:
  `datalake-normalize`가 raw를 읽어
  `<ROOT>/normalized/<table>/dt=YYYY-MM-DD/part-000.parquet`로 물질화.
- **데이터 모델의 단일 진실은 `datalake/model.py`** — 테이블 10개의
  pyarrow 스키마·자연키·병합 규칙. Parquet에 스키마가 내장되므로 소비자는
  DDL 없이 타입을 안다. 테이블은 hub 정규화 스키마와 동형이되 market만
  JSON snapshots 대신 `market_quotes`로 평탄화(kind: index/indicator/quote_us/quote_kr).
- 파티션 의미: 그 날짜(UTC)에 관측된 행. 파티션 내 dedup은 키 기준
  (dim류는 non-null 병합 + first/last_seen min/max — hub 업서트 동형),
  파티션 간 전역 dedup은 소비 측 몫. 파티션 통째 재작성 = 멱등.
- 소비: DuckDB·pandas 직독, Postgres는 `pg_duckdb`/`parquet_s3_fdw` 외부
  테이블(권장) 또는 정기 COPY 로딩. 순정 `file_fdw`는 CSV 전용이라 부적합.

## 6. 권장 스케줄 (hub와 동일 — 오케스트레이터 설정용 문서)

주기 env는 두지 않는다 — 스케줄은 오케스트레이터 설정이 유일한 진실이다.

| 명령 | 권장 주기 |
|---|---|
| `datalake-quake` | 60s |
| `datalake-news` | 120s |
| `datalake-trend` | 60s |
| `datalake-market` | 장중 45s / 장외 600s (hub 실효 TTL을 스케줄로 재현) |
| `datalake-contrail --scope regions` | 60s (프리셋 4개는 내부 순차 1.1s) |
| `datalake-contrail --scope global` | 600s |
| `datalake-wake --duration N` | 상시 또는 겹치지 않는 구간 반복 (`DATALAKE_FLUSH_S=10`) |
| `datalake-flashpoint` | 900s — 파일 중복은 상태 파일로 스킵, GDELT 게시 지연 404는 코드 1로 재시도 위임 |
| `datalake-normalize` | 시간당 1회 (당일 파티션 재작성) + 자정 후 전일 확정 1회 |
| `datalake-maintenance` | 일 1회 |

## 7. 리스크 / 확인 항목

1. **AISStream 동시 연결**: hub와 같은 `WAKE_AIS_KEY`로 2개 연결 시 키당 연결
   제한에 걸릴 수 있음 → **datalake 전용 키 발급 권장** (`DATALAKE_AIS_KEY`,
   미설정 시 wake 소스 비활성 — hub의 no_key 저하 계약과 동일).
2. **YouTube 쿼터 공유**: hub(1,440콜/일) + datalake(1,440콜/일) ≈ 2,880유닛/일,
   기본 쿼터 10,000 내 여유. 단 같은 키 사용 사실을 README에 명시.
3. **yfinance/pykrx**: 비공식 라이브러리 — 호출량 2배가 되므로 datalake 쪽은
   hub와 동일 TTL 게이트를 반드시 적용 (30s 폴이 아니라 실효 45s/600s).
4. **adsb.lol 예의**: 무인증 공개 API — hub와 합산 트래픽이 2배. 주기 준수 +
   전용 UA 문자열로 식별 가능하게.
5. **디스크**: contrail raw가 지배적(일 300~400MB, gzip 후 ~40MB). 로컬 개발 시
   `DATALAKE_SOURCES`로 소스 선택 실행 가능하게.

## 8. 구현 단계

1. **스캐폴드 + quake** — pyproject, core(source/sinks/runner/config), FileSink,
   quake 클라이언트, `--once` 모드, 테스트 (독립성 import 검사 포함)
2. **news + trend** — RSS 15매체(설정은 hub config에서 값 복사, import 아님),
   YouTube 클라이언트
3. **contrail + wake** — 멀티 bbox 폴링, StreamCollector 구독 + 플러시 버퍼
4. **market** — yfinance/pykrx 클라이언트 + 장시간 게이트 이식
5. **SqliteSink 옵션** — schema.py + 멱등 INSERT + raw 재구축 스크립트
6. **운영** — mise task(`datalake:run`), README, gzip 로테이션, (향후) 컨테이너화

각 단계는 독립적으로 머지 가능하며, 1단계 완료 시점부터 레이크가 실동작한다.

## 9. 범위 외 (YAGNI)

- LLM 파생물 적재, curated 존, 스키마 레지스트리, Parquet 변환, S3 업로드,
  hub `lab.db` 백필 — 전부 raw 존이 쌓인 뒤 필요할 때.
- hub 쪽 코드 수정 일절 없음 (이 설계의 성공 조건이기도 함).

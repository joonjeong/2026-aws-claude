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
| A. 독립 패키지 + labkit 재사용 | `shared/datalake`를 별도 배포 단위로 만들고, 검증된 `labkit`(PollingCollector·StreamCollector·env 헬퍼·Archive)만 라이브러리로 재사용 | **채택** — 프로세스 완전 독립 + 코드 중복 최소, "통합 솔루션이 수집기를 import해 조합" 방향과 일치 |
| B. hub 모듈 collector import | hub 코드 직접 재사용 | 기각 — hub `app.*` config/전역 상태에 결합, 독립성 제약 위반 |
| C. 완전 무의존 | labkit도 안 쓰고 재구현 | 기각 — poller/stream/백오프 재구현은 순수 중복 |

labkit은 **라이브러리**이지 실행 중인 웹서비스가 아니므로 A는 독립성 제약을
위반하지 않는다. 단, labkit 인터페이스 변경 시 영향 확인 대상이 hub 6모듈 +
datalake로 늘어난다.

## 4. 아키텍처

```
shared/datalake/
├── pyproject.toml            # name="datalake", deps: labkit, httpx, feedparser, websockets
│                             # (market 채택 시 yfinance·pykrx 추가)
├── datalake/
│   ├── config.py             # DATALAKE_* env (labkit.config 헬퍼 사용)
│   ├── core/
│   │   ├── source.py         # SourceMeta, PollSource/StreamSource 프로토콜, Record
│   │   ├── sinks.py          # FileSink(기본), SqliteSink(옵션)
│   │   └── runner.py         # 소스 → labkit 폴러/스트림 조립, 상태 리포트
│   ├── sources/              # ★ 재사용 가능한 코어 클라이언트 (모듈당 1파일)
│   │   ├── quake.py          #   fetch()/normalize() 순수 함수 + Client 클래스
│   │   ├── news.py           #   부작용 없음 — sink·저장을 모름
│   │   ├── trend.py
│   │   ├── market.py
│   │   ├── contrail.py
│   │   └── wake.py
│   ├── schema.py             # SQLite 옵션용 DDL (hub 정규화 테이블과 동형)
│   └── __main__.py           # python -m datalake run [--sources ...] [--once]
└── tests/
```

**코어 클라이언트 계약** — 각 `sources/<id>.py`는:
- `META: SourceMeta` — id, kind 목록, 모드(poll/stream), 기본 주기(hub와 동일 값)
- `class Client` — `fetch() -> list[Record]` (poll) 또는 `subscribe(on_record)` (stream).
  `Record = (kind, meta, payload_raw)`. 원본 페이로드를 그대로 반환.
- `normalize(payload) -> rows` — hub와 동일한 정규화 (SQLite 싱크·후속 소비자용)
- 저장·경로·DB를 일절 모름 → hub든 통합 솔루션이든 그대로 import 가능

**독립성 보장:**
- `hub.*` / `app.*` import 금지 (테스트로 강제: import 그래프 검사)
- 자체 데이터 루트 `DATALAKE_ROOT` (기본 `shared/datalake/data/`, gitignore)
- `lab.db` 경로를 알지도 못함. SQLite 옵션은 자체 `datalake.db`
- 별도 프로세스 (`python -m datalake run`), 향후 별도 컨테이너
- hub와 코드 공유는 labkit(라이브러리)뿐

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

### 5.2 SQLite 옵션 (`DATALAKE_SQLITE=1`)

- 자체 파일 `<DATALAKE_ROOT>/datalake.db`, labkit `Archive` 클래스 재사용
  (WAL·스키마 레지스트리·프루닝 검증 로직 그대로).
- 테이블은 hub 정규화 스키마와 **동형**(quake_events, news_articles,
  trend_videos/stats, contrail/wake dim+fact, market은 snapshots JSON):
  이미 검증된 스키마라 학습 비용 0, hub DB와 조인·비교도 쉬움.
- raw 존이 진실의 원천(source of truth), SQLite는 조회 편의용 파생 존.
  유실 시 raw에서 재구축 가능해야 함 → INSERT는 전부 멱등(OR IGNORE/UPSERT).

## 6. 수집 주기 (hub와 동일)

| 소스 | 주기 | env (기본값 = hub 기본값) |
|---|---|---|
| quake | 60s | `DATALAKE_QUAKE_INTERVAL_S=60` |
| news | 매체당 120s | `DATALAKE_NEWS_INTERVAL_S=120` |
| trend | 60s | `DATALAKE_TREND_INTERVAL_S=60` |
| market | 30s 폴 + 장중 45s/장외 600s 실효 게이트 (hub `hours.py` 로직 이식) | `DATALAKE_MARKET_INTERVAL_S=30` |
| contrail | 전세계 600s + 프리셋 4개 60s | `DATALAKE_CONTRAIL_GLOBAL_S=600`, `_REGION_S=60` |
| wake | 상시 WebSocket (hub와 동일 프리셋 bbox 구독) | 주기 없음, `DATALAKE_FLUSH_S=10` |
| flashpoint | 900s, 파일 단위 중복 스킵. raw는 필터 전 CSV 전문 보존(SQLite만 hub 동형 필터) | `DATALAKE_FLASHPOINT_INTERVAL_S=900` |

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

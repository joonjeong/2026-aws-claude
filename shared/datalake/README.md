# datalake — 독립 원본 데이터레이크

hub의 7개 모듈이 보는 것과 동일한 외부 상류를 **hub와 완전히 독립적으로**
수집해 메달리온 레이크에 적재한다. hub는 정규화본만 남기고 원본을 버리며
fact는 7~30일 프루닝되지만, 레이크는 전 필드를 보존한다.

- 설계: `docs/specs/2026-08-11-datalake-design.md`
- 개요: `docs/datalake.md`

## 아키텍처 (v0.8) — 수집이 경량 ETL까지

```
uv run datalake-<source> [--output <root>]        ← 모든 명령에 출력 루트 파라미터
   │ fetch 1회
   ├─▶ landing/<source>/<kind>/dt=…/part-HH.jsonl    원본 봉투 그대로 (불변, 진실의 원천)
   └─▶ bronze/<table>/dt=…/part-HH.jsonl             약간의 ETL: 파싱·타입화된 행 append
                                                       (자기 fetch분만 딱 1회 파싱,
                                                        중복 허용 — dedup은 silver 몫)
uv run datalake-silver [--date D] [--tables t,..]
   bronze(파싱된 행) ─▶ 키 dedup·dim 병합 ─▶ silver/<table>/dt=…/part-000.parquet

uv run datalake-bronze [--date D] [--sources s,..]   ← 평시 불필요 — ETL 수정 후
   landing 원본 ─▶ bronze 파티션 통째 재파생            과거 파티션 복구용 (멱등)
```

- **봉투 의미론**: `source` = 실제 상류(usgs_feed, bbc, adsblol …),
  `kind` = 생산 데이터셋(quake, news, contrail_region_kr …).
  한 상류가 여러 kind를 생산할 수 있다 (adsblol → contrail 5개).
- **존 의미 (일반적 메달리온과 1:1)**: landing=원본 바이트 ·
  bronze=무가공 파싱 레코드(append, 중복 허용) · silver=dedup·정합 Parquet ·
  gold=예약(집계·마트). `_state/`는 수집 상태(gdelt last_url, opensky 토큰 0600).
- **silver가 얇은 이유**: 파싱은 수집 시점에 끝났으므로 silver는 JSONL 행
  읽기 + dedup + 컬럼화뿐. bronze가 테이블별 경로라 `--tables` 프루닝이
  파일 수준에서 공짜. (구 normalize의 "매시간 그날 전체 재파싱" 구조 해소)
- **수집 대상은 목록 파일이 관리**: RSS 매체 `sources/rss_feeds.toml`
  (`DATALAKE_RSS_FEEDS`), market 심볼·지수·지표 `sources/market_symbols.toml`
  (`DATALAKE_MARKET_SYMBOLS`). 대상 추가 = 항목 1개, 코드 무변경.

## 구조 원칙

- **완전 독립**: `hub.*`/`app.*`/`labkit` import 금지 —
  `tests/test_independence.py`가 AST 검사로 강제. 의존성은
  httpx·feedparser·websockets·pyarrow·yfinance·pykrx.
- **상류별 순수 클라이언트** (`datalake/sources/`) + **one-shot CLI**
  (`datalake/cli/`): 1회 수집→적재 후 종료.
  종료 코드: 0 성공 / 1 실패 / 2 상류 비활성.
- **스케줄링 없음**: 케이던스·재시도는 외부 스케줄러 소유 (cron이든 뭐든).
  명령은 `--output`으로 어디서든 조립 가능.
- **DB 없음 — 파일이 인터페이스**: DB(Postgres 등)는 silver를 외부
  테이블(FDW)로 연결해서만 사용.

## silver 데이터 모델 (`datalake/model.py`가 단일 진실)

테이블 10개의 컬럼·타입(pyarrow 스키마)·자연키·병합 규칙을 코드로 정의.
Parquet에 스키마가 내장되므로 소비자는 별도 DDL 없이 타입을 안다.

| 테이블 | 키 | 공급 상류 |
|---|---|---|
| quake_events | id | usgs_feed |
| news_articles | link | rss 목록의 매체들 (15) |
| trend_videos / trend_video_stats | video_id / (video_id, ts) | youtube |
| contrail_aircraft / contrail_positions | icao24 / (icao24, ts) | adsblol + opensky (**제공자 중립**) |
| wake_vessels / wake_positions | mmsi / (mmsi, ts) | aisstream |
| flashpoint_events | event_id | gdelt (CAMEO 루트 14~20 필터) |
| market_quotes | (kind, symbol, ts) | yfinance + pykrx |

파티션(dt=) 의미: **그 날짜(UTC)에 관측된 행**. 파티션 내 dedup은 silver
생성 시(dim류는 non-null 병합 + first/last_seen min/max — hub 업서트 동형),
파티션 간 전역 dedup은 소비 측 몫(`SELECT DISTINCT ON (key)`).

landing만이 진실: bronze는 `datalake-bronze`로, silver는 `datalake-silver`로
언제든 재생성된다. gdelt landing은 CAMEO 필터 **전** CSV 전문을 보존.

## DB에서 소비하기 (Postgres 등)

```sql
-- DuckDB (즉석 분석·검증) — bronze(JSONL)도 silver(Parquet)도 직독
SELECT * FROM read_parquet('data/silver/quake_events/*/*.parquet');
SELECT * FROM read_json_auto('data/bronze/quake_events/*/*.jsonl');

-- Postgres: pg_duckdb 또는 parquet_s3_fdw로 silver를 외부 테이블 연결(권장)
--   dt= Hive 파티션 → dt 조건이 파티션 프루닝으로 동작
-- 확장 불가 환경: 정기 COPY 로딩 잡으로 실체화
```

## 명령과 권장 스케줄 (수집 주기는 hub 기본값과 동일)

| 명령 (`uv run …`) | 생산 | 권장 스케줄 | 활성 조건 |
|---|---|---|---|
| `datalake-usgs-feed` | quake | 60s | 항상 |
| `datalake-rss [--feeds bbc,yna] [--list]` | news (목록 파일 관리) | 120s | 항상 |
| `datalake-youtube` | trend | 60s | `YT_API_KEY` |
| `datalake-adsblol --scope regions\|global` | contrail_* | 60s / 600s | 항상 |
| `datalake-opensky --scope …` | 동일 (adsblol과 수렴) | 동일 | 항상 (인증 권장) |
| `datalake-aisstream --duration 300` | wake | 상시 또는 겹치지 않는 구간 | `DATALAKE_AIS_KEY` |
| `datalake-yfinance [--kinds …]` | market_overview·quotes_us | 장중 45s / 장외 600s | 항상 |
| `datalake-pykrx` | market_quotes_kr | 장중 45s / 장외 600s | 항상 |
| `datalake-gdelt [--force]` | flashpoint | 900s | 항상 |
| `datalake-silver [--date D] [--tables t,..]` | bronze → silver Parquet (멱등) | 시간당 + 자정 후 전일 확정 | — |
| `datalake-bronze [--date D] [--sources s,..]` | landing → bronze 재파생 (멱등) | 평시 불필요 (ETL 수정 후) | — |
| `datalake-maintenance` | landing·bronze 전일 gzip + 보존 프루닝 | 일 1회 | — |

```bash
cd shared/datalake && uv sync
mise run datalake:smoke              # 무키 상류 스모크
mise run datalake:test               # 테스트
```

## env

| 변수 | 기본 | 설명 |
|---|---|---|
| `DATALAKE_ROOT` | `shared/datalake/data` | 레이크 루트 (`--output`이 우선) |
| `DATALAKE_FLUSH_S` | `10` | aisstream 버퍼 플러시 주기 |
| `DATALAKE_COMPRESS` | `1` | maintenance의 전일 파티션 gzip |
| `DATALAKE_RAW_RETENTION_DAYS` | `0` (무제한) | landing·bronze 보존기간 |
| `DATALAKE_RSS_FEEDS` | 패키지 내장 `rss_feeds.toml` | RSS 수집 대상 목록 파일 |
| `DATALAKE_MARKET_SYMBOLS` | 패키지 내장 `market_symbols.toml` | market 심볼 목록 파일 |
| `DATALAKE_AISSTREAM_PRESET` | `kr` | aisstream 관심 해역 (kr/taiwan/sea) |
| `DATALAKE_OPENSKY_CLIENT_ID/SECRET` | — | OpenSky OAuth2 (없으면 익명 감속) |
| `DATALAKE_MARKET_ACTIVE_US/KR` | `20` | 활성 심볼 수 |
| `YT_API_KEY` | — | youtube (hub와 **공유**) |
| `DATALAKE_AIS_KEY` | — | aisstream (hub와 공유 **금지**) |

## 운영 주의

1. **AISStream**: 키당 동시 연결 제한 — hub `WAKE_AIS_KEY` 재사용 금지,
   전용 키 발급. 미설정 시 aisstream만 종료 코드 2.
2. **YouTube 쿼터**: hub와 키 공유 시 합산 ≈ 2,880유닛/일 (기본 쿼터 내).
3. **yfinance/pykrx**: 비공식 라이브러리 — 장중 45s/장외 600s 권장 스케줄로
   hub와 합산 호출량 관리. pykrx의 "KRX 로그인 실패" 출력은 무해
   (로그인 불필요한 종목별 경로 사용).
4. **adsb.lol**: 프리셋 조회는 클라이언트가 내부 순차 1.1s 간격 준수
   (병렬 4요청 → 420 실측). 스케줄 60s 미만 금지.
5. **OpenSky**: 데이터센터 IP 차단 실측 — 클라우드에서는 adsblol 사용.
6. **GDELT 404**: lastupdate.txt 갱신 후 zip 게시가 늦는 경우 존재 —
   코드 1 종료, 다음 스케줄 실행이 곧 재시도.
7. **mk RSS**: 2026-08-11 기준 전 UA 403 (상류 측 차단) — 매체 격리로
   나머지 무영향, 지속 시 목록 파일에서 피드 URL 교체.
8. **디스크**: adsblol 전세계 landing이 지배적(일 300~400MB, gzip 후 ~40MB).
   `datalake-maintenance` 일 1회 필수.

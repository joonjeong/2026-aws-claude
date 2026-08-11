# datalake — 독립 원본 데이터레이크

hub의 7개 모듈이 보는 것과 동일한 외부 상류를 **hub와 완전히 독립적으로**
수집해 원본(raw)을 그대로 메달리온 레이크에 적재한다. hub는 정규화본만
남기고 원본을 버리며 fact는 7~30일 프루닝되지만, 레이크는 전 필드를 보존한다.

- 설계: `docs/specs/2026-08-11-datalake-design.md`
- 개요: `docs/datalake.md`

## 봉투 의미론 (v0.5)

- **`source` = 실제 상류**(usgs_feed, bbc, adsblol, opensky, aisstream, …)
- **`kind` = 생산되는 데이터셋**(quake, news, contrail_region_kr, wake, …)
- **명령 = 상류 단위** — `uv run datalake-<source>`. 한 상류가 여러
  데이터셋을 생산할 수 있다 (adsblol → contrail_global + region 4개).
- 같은 데이터셋을 여러 상류가 공급하면(contrail: adsblol/opensky) bronze는
  source로 경로가 갈리고, silver에서 같은 제공자 중립 테이블로 수렴한다.

```
bronze/<source>/<kind>/dt=YYYY-MM-DD/part-HH.jsonl[.gz]
한 줄 = {"fetched_at","source","kind","meta","payload(원본)"}
```

## 구조 원칙

- **완전 독립**: `hub.*`/`app.*`/`labkit` import 금지 —
  `tests/test_independence.py`가 AST 검사로 강제. 의존성은
  httpx·feedparser·websockets·pyarrow뿐.
- **상류별 순수 클라이언트** (`datalake/sources/`): fetch/normalize만 —
  저장·경로·스케줄을 모른다.
- **상류별 one-shot CLI** (`datalake/cli/`): 클라이언트를 래핑해
  1회 수집→적재 후 종료. 종료 코드: 0 성공 / 1 실패 / 2 상류 비활성.
- **스케줄링 없음**: 케이던스·재시도·백오프는 외부 오케스트레이터
  (Temporal 도입 예정) 소유.
- **DB 없음 — 파일이 인터페이스**: 수집은 bronze에만 쓰고,
  `datalake-normalize`가 스키마 내장 Parquet(silver)으로 물질화.
  DB(Postgres 등)는 파일을 외부 테이블(FDW)로 연결해서만 사용.

## 저장 구조 — 메달리온 존

```
data/                                  # DATALAKE_ROOT (gitignore)
├── bronze/<source>/<kind>/dt=…/part-HH.jsonl[.gz]   # 진실의 원천
├── silver/<table>/dt=…/part-000.parquet             # 정규화 소비 존
├── gold/                              # 예약 — 집계·마트·LLM 파생물
└── _state/                            # one-shot 실행 간 소량 상태
                                       #   (gdelt last_url, opensky 토큰 0600)
```

**silver의 데이터 모델은 `datalake/model.py`가 단일 진실** — 테이블 10개의
컬럼·타입(pyarrow 스키마)·자연키·파티션 내 병합 규칙. Parquet에 스키마가
내장되므로 소비자는 별도 DDL 없이 타입을 안다.

| 테이블 | 키 | 공급 상류 |
|---|---|---|
| quake_events | id | usgs_feed |
| news_articles | link | bbc·guardian·…·wapo (15) |
| trend_videos / trend_video_stats | video_id / (video_id, ts) | youtube |
| contrail_aircraft / contrail_positions | icao24 / (icao24, ts) | adsblol + opensky (**제공자 중립**) |
| wake_vessels / wake_positions | mmsi / (mmsi, ts) | aisstream |
| flashpoint_events | event_id | gdelt (CAMEO 루트 14~20 필터) |
| market_quotes | (kind, symbol, ts) | yfinance + pykrx — kind: index·indicator·quote_us·quote_kr |

파티션 의미: **그 날짜(UTC)에 관측된 행**. 파티션 내 dedup은 생성 시
키로 수행(dim류는 non-null 병합 + first/last_seen min/max — hub 업서트와
동형), 파티션 간 전역 dedup은 소비 측 몫(`SELECT DISTINCT ON (key)`).
`datalake-normalize`는 파티션을 통째로 재작성하므로 재실행이 곧 멱등.

bronze만이 진실이며 silver는 언제든 재생성 가능하다. gdelt bronze는
CAMEO 필터 **전** CSV 전문을 보존하고, 필터는 normalize 단계에서만 적용된다.

## DB에서 소비하기 (Postgres 등)

```sql
-- DuckDB (즉석 분석·검증)
SELECT * FROM read_parquet('data/silver/quake_events/*/*.parquet');

-- Postgres: pg_duckdb 또는 parquet_s3_fdw 확장으로 외부 테이블 연결(권장)
--   silver/<table>/dt=…  Hive 파티션 → dt 조건이 파티션 프루닝으로 동작
-- 확장 불가 환경: 정기 COPY 로딩 잡으로 실체화
```

순정 `file_fdw`는 CSV 전용·단일 파일이라 이 레이아웃과 맞지 않는다.

## 명령과 권장 스케줄 (수집 주기는 hub 기본값과 동일)

| 명령 (`uv run …`) | 생산 kind | 권장 스케줄 | 활성 조건 |
|---|---|---|---|
| `datalake-usgs-feed` | quake | 60s | 항상 |
| `datalake-bbc` … `datalake-wapo` (매체별 15개) | news | 120s | 항상 |
| `datalake-youtube` | trend | 60s | `YT_API_KEY` |
| `datalake-adsblol --scope regions\|global` | contrail_region_* / contrail_global | 60s / 600s | 항상 |
| `datalake-opensky --scope …` | 동일 (adsblol과 수렴) | 동일 | 항상 (인증 권장) |
| `datalake-aisstream --duration 300` | wake | 상시 또는 겹치지 않는 구간 | `DATALAKE_AIS_KEY` |
| `datalake-yfinance [--kinds …]` | market_overview, market_quotes_us | 장중 45s / 장외 600s | `--extra market` |
| `datalake-pykrx` | market_quotes_kr | 장중 45s / 장외 600s | `--extra market` |
| `datalake-gdelt [--force]` | flashpoint | 900s | 항상 |
| `datalake-normalize [--date D] [--tables t,..]` | bronze → silver (멱등) | 시간당 + 자정 후 전일 확정 | — |
| `datalake-maintenance` | 전일 bronze gzip + 보존 프루닝 | 일 1회 | — |

```bash
cd shared/datalake && uv sync        # 준비 (market까지: uv sync --extra market)
mise run datalake:smoke              # 무키 상류 스모크 (usgs-feed·bbc·gdelt)
mise run datalake:test               # 테스트
```

## env

| 변수 | 기본 | 설명 |
|---|---|---|
| `DATALAKE_ROOT` | `shared/datalake/data` | 레이크 루트 |
| `DATALAKE_FLUSH_S` | `10` | aisstream 버퍼 플러시 주기 |
| `DATALAKE_COMPRESS` | `1` | maintenance의 전일 bronze gzip |
| `DATALAKE_RAW_RETENTION_DAYS` | `0` (무제한) | maintenance의 bronze 보존기간 |
| `DATALAKE_AISSTREAM_PRESET` | `kr` | aisstream 관심 해역 (kr/taiwan/sea) |
| `DATALAKE_OPENSKY_CLIENT_ID/SECRET` | — | OpenSky OAuth2 (없으면 익명 감속) |
| `DATALAKE_MARKET_ACTIVE_US/KR` | `20` | yfinance/pykrx 활성 심볼 수 |
| `YT_API_KEY` | — | youtube (hub와 **공유**) |
| `DATALAKE_AIS_KEY` | — | aisstream (hub와 공유 **금지**) |

## 운영 주의 (설계 §7)

1. **AISStream**: 키당 동시 연결 제한 — hub의 `WAKE_AIS_KEY`를 재사용하지 말고
   전용 키를 발급할 것. 미설정 시 aisstream만 종료 코드 2로 비활성.
2. **YouTube 쿼터**: hub와 같은 키 사용 시 합산 ≈ 2,880유닛/일 (기본 쿼터
   10,000 내).
3. **yfinance/pykrx**: 비공식 라이브러리 — 권장 스케줄(장중 45s/장외 600s)을
   지켜 hub와 합산 호출량을 관리할 것.
4. **adsb.lol**: 프리셋 조회는 클라이언트가 내부에서 순차 1.1s 간격을 지킨다
   (병렬 4요청 → 420 실측). 스케줄을 60s 미만으로 줄이지 말 것.
5. **OpenSky**: 데이터센터 IP 차단 실측 — 클라우드에서는 adsblol 사용.
   익명 모드는 감속되므로 60s 스케줄에는 인증 권장.
6. **GDELT 404**: lastupdate.txt 갱신 후 zip 게시가 늦는 경우가 있다 —
   코드 1로 끝나며 다음 스케줄 실행이 곧 재시도다.
7. **디스크**: adsblol 전세계 bronze가 지배적(일 300~400MB, gzip 후 ~40MB).
   `datalake-maintenance`를 일 1회 스케줄에 포함할 것.

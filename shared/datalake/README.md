# datalake — 독립 원본 데이터레이크

hub의 7개 모듈이 보는 것과 동일한 외부 소스를 **hub와 완전히 독립적으로**
수집해 원본(raw) 그대로 디렉토리 레이크에 적재한다. hub는 정규화본만
남기고 원본을 버리며 fact는 7~30일 프루닝되지만, 레이크는 전 필드를 보존한다.

- 설계: `docs/specs/2026-08-11-datalake-design.md`
- 플랜: `docs/plans/2026-08-11-datalake.md`

## 구조 원칙 (v0.3)

- **완전 독립**: `hub.*`/`app.*`/`labkit` import 금지 —
  `tests/test_independence.py`가 AST 검사로 강제. 의존성은
  httpx·feedparser·websockets·pyarrow뿐.
- **소스별 순수 클라이언트** (`datalake/sources/`): fetch/normalize만 —
  저장·경로·스케줄을 모른다.
- **소스별 one-shot CLI** (`datalake/cli/`): 클라이언트를 래핑해
  1회 수집→적재 후 종료. `uv run datalake-<source>`로 독립 실행.
- **스케줄링 없음**: 케이던스·재시도·백오프는 외부 오케스트레이터
  (Temporal 도입 예정) 소유. 종료 코드: 0 성공 / 1 실패 / 2 소스 비활성.
- **DB 없음 — 파일이 인터페이스**: 수집은 raw JSONL에만 쓰고,
  `datalake-normalize`가 스키마 내장 Parquet으로 물질화한다.
  DB(Postgres 등)는 파일을 **로딩·연결해서만** 사용 (아래 소비 가이드).

## 저장 구조와 데이터 모델

```
data/                                  # DATALAKE_ROOT (gitignore)
├── raw/<source>/<kind>/dt=YYYY-MM-DD/part-HH.jsonl[.gz]     # 진실의 원천
│     한 줄 = {"fetched_at","source","kind","meta","payload(원본)"}
├── normalized/<table>/dt=YYYY-MM-DD/part-000.parquet        # 소비용 파생 존
└── state/                             # one-shot 실행 간 소량 상태
```

**정규화 모델은 `datalake/model.py`가 단일 진실** — 테이블 10개의
컬럼·타입(pyarrow 스키마)·자연키·파티션 내 병합 규칙을 코드로 정의하고,
Parquet 파일에 스키마가 내장되므로 소비자는 별도 DDL 없이 타입을 안다.

| 테이블 | 키 | 내용 |
|---|---|---|
| quake_events | id | USGS 지진 이벤트 |
| news_articles | link | RSS 기사 (HTML 제거, 요약 300자) |
| trend_videos / trend_video_stats | video_id / (video_id, ts) | YouTube dim / 60s 버킷 순위 fact |
| contrail_aircraft / contrail_positions | icao24 / (icao24, ts) | 항공기 dim / 위치 fact |
| wake_vessels / wake_positions | mmsi / (mmsi, ts) | 선박 dim / 위치 fact |
| flashpoint_events | event_id | GDELT 분쟁 이벤트 (CAMEO 루트 14~20) |
| market_quotes | (kind, symbol, ts) | 시세 평탄화 — kind: index·indicator·quote_us·quote_kr |

파티션 의미: **그 날짜(UTC)에 관측된 행**. 파티션 내 dedup은 생성 시
키로 수행(dim류는 non-null 병합 + first/last_seen min/max — hub 업서트와
동형), 파티션 간 전역 dedup은 소비 측 몫(`SELECT DISTINCT ON (key)`).
`datalake-normalize`는 파티션 파일을 통째로 재작성하므로 재실행이 곧 멱등.

raw만이 진실이며 normalized는 언제든 재생성 가능하다. flashpoint raw는
CAMEO 필터 **전** CSV 전문을 보존하고, 필터는 normalize 단계에서만 적용된다.

## DB에서 소비하기 (Postgres 등)

수집기는 DB를 모른다 — 파일을 연결하거나 로딩한다:

```sql
-- DuckDB (즉석 분석·검증)
SELECT * FROM read_parquet('data/normalized/quake_events/*/*.parquet');

-- Postgres + pg_duckdb 또는 parquet_s3_fdw: 외부 테이블로 직조회
-- Postgres 순정만 쓸 경우: 정기 COPY 로딩
--   psql로 duckdb/pyarrow가 뽑은 CSV를 COPY하거나, 파티션별 적재 잡 구성
```

권장: `pg_duckdb`(또는 `parquet_s3_fdw`)로 normalized 존을 외부 테이블로
붙이는 방식 — dt= 파티션 프루닝이 그대로 동작한다. 순정 `file_fdw`는
CSV만 읽으므로 이 레이아웃과 맞지 않는다.

## 명령과 권장 스케줄 (수집 주기는 hub 기본값과 동일)

| 명령 | 소스 | 권장 스케줄 | 활성 조건 |
|---|---|---|---|
| `uv run datalake-quake` | USGS GeoJSON | 60s | 항상 |
| `uv run datalake-news [--feeds bbc,yna]` | RSS 15매체 | 120s | 항상 |
| `uv run datalake-trend` | YouTube mostPopular(KR) | 60s | `YT_API_KEY` |
| `uv run datalake-contrail --scope regions` | adsb.lol 프리셋 4개 (순차 1.1s) | 60s | 항상 |
| `uv run datalake-contrail --scope global` | adsb.lol 전세계 | 600s | 항상 |
| `uv run datalake-wake --duration 300` | AISStream 스트림 | 상시 또는 겹치지 않는 구간 실행 | `DATALAKE_AIS_KEY` |
| `uv run datalake-market` | yfinance·pykrx | 장중 45s / 장외 600s | `uv sync --extra market` |
| `uv run datalake-flashpoint` | GDELT 15분 export | 900s | 항상 |
| `uv run datalake-normalize [--date D] [--tables t,..]` | raw → Parquet 물질화 (멱등) | 시간당 1회 + 자정 후 전일 확정 1회 | — |
| `uv run datalake-maintenance` | 전일 raw gzip + 보존 프루닝 | 일 1회 | — |

```bash
cd shared/datalake && uv sync        # 준비 (market까지: uv sync --extra market)
mise run datalake:smoke              # 무키 소스 스모크
mise run datalake:test               # 테스트
```

## env

| 변수 | 기본 | 설명 |
|---|---|---|
| `DATALAKE_ROOT` | `shared/datalake/data` | 레이크 루트 |
| `DATALAKE_FLUSH_S` | `10` | wake 스트림 버퍼 플러시 주기 |
| `DATALAKE_COMPRESS` | `1` | maintenance의 전일 raw gzip |
| `DATALAKE_RAW_RETENTION_DAYS` | `0` (무제한) | maintenance의 raw 보존기간 |
| `DATALAKE_WAKE_PRESET` | `kr` | wake 관심 해역 (kr/taiwan/sea) |
| `YT_API_KEY` | — | trend (hub와 **공유**) |
| `DATALAKE_AIS_KEY` | — | wake (hub와 공유 **금지**) |

## 운영 주의 (설계 §7)

1. **AISStream**: 키당 동시 연결 제한 — hub의 `WAKE_AIS_KEY`를 재사용하지 말고
   전용 키를 발급할 것. 미설정 시 wake만 종료 코드 2로 비활성.
2. **YouTube 쿼터**: hub와 같은 키 사용 시 합산 ≈ 2,880유닛/일 (기본 쿼터
   10,000 내).
3. **yfinance/pykrx**: 비공식 라이브러리 — 권장 스케줄(장중 45s/장외 600s)을
   지켜 hub와 합산 호출량을 관리할 것.
4. **adsb.lol**: 프리셋 조회는 클라이언트가 내부에서 순차 1.1s 간격을 지킨다
   (병렬 4요청 → 420 실측). 스케줄을 60s 미만으로 줄이지 말 것.
5. **flashpoint 404**: GDELT가 lastupdate.txt를 먼저 갱신하고 zip 게시가
   늦는 경우가 있다 — 코드 1로 끝나며 다음 스케줄 실행이 곧 재시도다.
6. **디스크**: contrail 전세계 raw가 지배적(일 300~400MB, gzip 후 ~40MB).
   `datalake-maintenance`를 일 1회 스케줄에 포함할 것.

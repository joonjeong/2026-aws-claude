# datalake — 독립 원본 데이터레이크 개요

작성 2026-08-11 · 코드 `shared/datalake` · 설계 `docs/specs/2026-08-11-datalake-design.md` · PR #1

## 1. 무엇인가

hub의 7개 모듈(quake·news·trend·market·contrail·wake·flashpoint)이 보는 것과
동일한 외부 소스를 **hub와 완전히 독립적으로** 수집해, 원본(raw)을 그대로
디렉토리 레이크에 보존하는 배치 도구 모음이다.

hub는 서빙이 목적이라 정규화본만 남기고 원본을 버리며 fact 테이블은 7~30일
후 프루닝되고, Fargate 재시작 시 DB 자체가 사라진다. 레이크는 그 공백을
채운다: **원본 전 필드, 영구 보존, 스키마 있는 소비용 파생 존**.

## 2. 전체 아키텍처

```
[외부 소스]                [one-shot CLI (uv run …)]        [데이터레이크 DATALAKE_ROOT]

USGS 지진 피드 ──60s──▶ datalake-usgs-feed ─┐
RSS 매체 15개 ──120s──▶ datalake-rss (목록 파일) ┤
YouTube API ────60s──▶ datalake-youtube ─────┤   bronze/<source>/<kind>/dt=YYYY-MM-DD/part-HH.jsonl[.gz]
adsb.lol ──60s·600s──▶ datalake-adsblol ─────┼─▶ 한 줄 = {"fetched_at","source","kind","meta","payload(원본)"}
OpenSky ───60s·600s──▶ datalake-opensky ─────┤   source = 상류, kind = 데이터셋 ◀── 진실의 원천
AISStream ────상시───▶ datalake-aisstream ───┤                  │
yfinance ──45s/600s──▶ datalake-yfinance ────┤                  │  datalake-normalize
pykrx ─────45s/600s──▶ datalake-pykrx ───────┤                  │  (시간당, 파티션 재작성 = 멱등)
GDELT export ──900s──▶ datalake-gdelt ───────┘                  │
                                                                ▼
                                            silver/<table>/dt=YYYY-MM-DD/part-000.parquet
                                            ◀── 정규화 소비 존 (zstd, pyarrow 스키마 내장)
                                                                │           gold/ (예약 — 집계·마트)
                          ┌─────────────────────────────────────┼──────────────────────┐
                          ▼                                     ▼                      ▼
                    DuckDB 직독                    Postgres 외부 테이블            pandas/Arrow
              read_parquet('…/*.parquet')       (pg_duckdb · parquet_s3_fdw)
```

존 네이밍은 메달리온 아키텍처(bronze/silver/gold)를 따른다 — gold는 향후
집계·마트·LLM 파생물용 예약, `_state/`는 one-shot 실행 간 소량 상태
(flashpoint last_url, OpenSky 토큰 캐시). 보조 명령:
`datalake-maintenance`(일 1회 — 전일 bronze gzip + 보존 프루닝).

**봉투 의미론 (v0.5~0.6)**: `source` = 실제 상류(usgs_feed, bbc, adsblol …),
`kind` = 생산 데이터셋(quake, news, contrail_region_kr …). 명령도 상류
단위이며 한 상류가 여러 kind를 생산할 수 있다(adsblol → contrail 5개).
RSS처럼 포맷이 표준이면 명령 하나(`datalake-rss`)가 목록 파일
(rss_feeds.toml)의 매체들을 순회한다 — 봉투의 source=매체는 유지.
같은 데이터셋을 여러 상류가 공급하면(contrail: adsblol/opensky) bronze는
source로 경로가 갈리고 silver의 제공자 중립 테이블로 수렴 —
(icao24, ts) 키가 겹침을 병합한다.

## 3. hub와의 독립성 경계

```
┌────────────────────── hub (상시 웹서비스) ──────────────────────┐
│  외부 소스 ─▶ 모듈 폴러 ─▶ 인메모리 스토어 ─▶ API·프론트·LLM 브리핑  │
│                     └─▶ lab.db (정규화만, fact 7~30일 프루닝)     │
└─────────────────────────────────────────────────────────────────┘
        ▲  같은 소스를 바라보지만 코드·프로세스·저장소 완전 분리
        │  (공유 코드 0 — labkit도 v0.2에서 제거)
┌────────────────────── datalake (one-shot 배치) ─────────────────┐
│  외부 소스 ─▶ 순수 클라이언트 ─▶ bronze JSONL (원본 전체, 영구)       │
│                                └─▶ silver Parquet (파생)       │
└─────────────────────────────────────────────────────────────────┘
```

독립성은 테스트로 강제된다: `tests/test_independence.py`가 패키지 전체를
AST 파싱해 `hub.*`/`app.*`/`labkit` import를 발견하면 실패한다.
의존성은 httpx·feedparser·websockets·pyarrow 4개뿐이며, hub의 `lab.db`
경로를 알지도 못한다. 어느 쪽이 죽어도 서로 영향이 없고, 외부에서 겹치는
것은 API 쿼터뿐이다(§8).

## 4. 코드 구조 — 클라이언트 / CLI / 모델의 분리

```
shared/datalake/datalake/
├── sources/            ★ 상류별 순수 클라이언트 — fetch·normalize만.
│   usgs_feed.py rss.py    저장·경로·스케줄을 모른다 → 어떤 소비자든
│   youtube.py adsblol.py   (향후 통합 솔루션 포함) 그대로 import 가능
│   opensky.py aisstream.py
│   yfinance.py pykrx.py gdelt.py
├── cli/                ★ 상류별 one-shot 명령 11개 (pyproject scripts)
│   usgs_feed.py rss.py youtube.py adsblol.py opensky.py
│   aisstream.py yfinance.py pykrx.py gdelt.py normalize.py maintenance.py
├── model.py            ★ 정규화 존 데이터 모델의 단일 진실 (pyarrow 스키마)
├── core/
│   ├── source.py       Record 봉투 타입
│   ├── sinks.py        FileSink (Hive 파티션 JSONL append)
│   ├── transform.py    Record → 테이블 행 (model.py 스펙과 짝)
│   ├── parquet.py      bronze 순회 + 파티션 물질화(materialize)
│   ├── stream.py       WebSocket 수집기 (백오프 재접속, connect 주입)
│   ├── maintenance.py  gzip·보존 프루닝
│   └── env.py          env 헬퍼
└── tests/              56개 — 독립성 게이트·정규화 동형성·멱등성·CLI 경로
```

## 5. 데이터 모델 (silver 존, `model.py`)

hub 정규화 스키마와 동형 — hub DB와 조인·비교가 쉽다. market만 JSON
스냅샷 대신 평탄화했다. Parquet에 스키마가 내장되므로 소비자는 DDL이
필요 없다.

| 테이블 | 자연키 | 병합 | 내용 |
|---|---|---|---|
| quake_events | id | 최초 관측 | USGS 지진 이벤트 (상류: usgs_feed) |
| news_articles | link | 최초 관측 | RSS 기사 (HTML 제거, 요약 300자 캡) |
| trend_videos | video_id | dim 병합 | YouTube 영상 메타 |
| trend_video_stats | (video_id, ts) | 최초 관측 | 60s 버킷 순위·조회수 fact |
| contrail_aircraft | icao24 | dim 병합 | 항공기 메타 |
| contrail_positions | (icao24, ts) | 최초 관측 | 위치 fact (전세계 스냅샷은 제외 — 홍수 방지) |
| wake_vessels | mmsi | dim 병합 | 선박 메타 (ITU-R 선종 라벨) |
| wake_positions | (mmsi, ts) | 최초 관측 | 위치 fact (AIS 센티널 → NULL) |
| flashpoint_events | event_id | 최초 관측 | GDELT 분쟁 이벤트 (CAMEO 루트 14~20) |
| market_quotes | (kind, symbol, ts) | 최초 관측 | 시세 평탄화 — kind: index·indicator·quote_us·quote_kr |

- **파티션 의미**: `dt=` 는 "그 날짜(UTC)에 관측된 행". 같은 자연키가 여러
  날짜에 나타날 수 있다(예: quake 2.5_day 피드). 전역 유일이 필요하면
  소비 측에서 `SELECT DISTINCT ON (key)`.
- **dim 병합** = 후속 관측의 non-null 필드가 갱신, first_seen=min /
  last_seen=max — hub의 COALESCE 업서트와 동형.
- bronze만이 진실: silver는 `datalake-normalize` 재실행으로 언제든 재생성.
- flashpoint raw는 CAMEO 필터 **전** CSV 전문을 보존 — hub가 버리는
  이벤트도 레이크에는 남는다.

## 6. 운영 모델 — 스케줄링은 오케스트레이터 소유

datalake에는 스케줄러·재시도·백오프가 **없다**. 향후 Temporal이 배치를
소유한다는 전제로 중복 기능을 제거했고, 계약은 종료 코드뿐이다:

```
Temporal 스케줄 ──▶ uv run datalake-usgs-feed    (매 60s)      ┐
               ──▶ uv run datalake-rss           (매 120s)     │ 종료 코드 계약
               ──▶ uv run datalake-youtube       (매 60s)      │   0 = 성공(0건 포함)
               ──▶ uv run datalake-adsblol --scope regions (60s) / global (600s)
               ──▶ uv run datalake-opensky --scope … (동일)    │   1 = 실패 → 재시도는
               ──▶ uv run datalake-yfinance      (장중 45s/장외 600s)   Temporal 정책
               ──▶ uv run datalake-pykrx         (장중 45s/장외 600s)
               ──▶ uv run datalake-gdelt         (매 900s)     │   2 = 상류 비활성
               ──▶ uv run datalake-aisstream --duration N (겹침 없는 구간)  (키·엑스트라 부재)
               ──▶ uv run datalake-normalize     (매시 + 자정 후 전일 확정)
               ──▶ uv run datalake-maintenance   (일 1회)      ┘
```

수집 주기 권장값은 hub 폴러 기본값과 동일하다(사용자 요구). 멱등성이
스케줄 실수를 흡수한다: 수집 재실행은 bronze append일 뿐이고(정규화 시 키
dedup), normalize 재실행은 파티션 재작성, flashpoint는 상태 파일로 같은
15분 파일을 스킵한다.

## 7. Postgres/FDW 소비

수집기는 DB를 모른다 — DB가 파일을 외부 테이블로 연결한다:

```sql
-- DuckDB (즉석 분석)
SELECT * FROM read_parquet('data/silver/quake_events/*/*.parquet');

-- Postgres: pg_duckdb 또는 parquet_s3_fdw 확장으로 외부 테이블 연결(권장)
--   silver/<table>/dt=…  Hive 파티션 → dt 조건이 파티션 프루닝으로 동작
-- 확장 불가 환경: 정기 COPY 로딩 잡으로 실체화
```

순정 `file_fdw`는 CSV 전용·단일 파일이라 이 레이아웃과 맞지 않는다.
(v0.1~0.2에 있던 SQLite 파생 존은 이 방향이 확정되며 제거됨.)

## 8. 운영 주의

| 항목 | 내용 |
|---|---|
| AISStream 키 | 키당 동시 연결 제한 — hub `WAKE_AIS_KEY` 재사용 금지, 전용 `DATALAKE_AIS_KEY` 발급. 미설정 시 wake만 코드 2 비활성 |
| YouTube 쿼터 | hub와 키 공유 시 합산 ≈ 2,880유닛/일 (기본 쿼터 10,000 내) |
| adsb.lol | 프리셋 4개는 클라이언트가 내부 순차 1.1s 간격 준수 (병렬 4요청 → 420 실측). 스케줄 60s 미만 금지 |
| yfinance·pykrx | 비공식 라이브러리 — 장중 45s/장외 600s 권장 스케줄로 hub와 합산 호출량 관리 |
| OpenSky | 데이터센터 IP 차단 실측 — 클라우드에서는 adsblol 제공자 사용. 익명 모드는 감속, 60s 스케줄에는 `DATALAKE_OPENSKY_CLIENT_ID/SECRET` 인증 권장 |
| GDELT 404 | lastupdate.txt 갱신 후 zip 게시가 늦는 경우 존재 — 코드 1 종료, 다음 스케줄이 곧 재시도 |
| 디스크 | contrail 전세계 bronze가 지배적 (일 300~400MB, gzip 후 ~40MB) — maintenance 일 1회 필수 |

## 9. 결정 이력

| 버전 | 결정 | 이유 |
|---|---|---|
| v0.1 | 독립 패키지 + labkit 재사용, Runner 상시 폴링, SQLite 옵션 | 최초 구현 — hub 수집과 동형 |
| v0.2 | labkit 제거(완전 무의존) · 소스별 one-shot CLI · 스케줄링 전면 제거 | 사용자 결정: 소스별 독립 실행 명령 + Temporal 도입 예정이라 중복 기능 제거 |
| v0.3 | SQLite 제거 · `model.py` 명시적 데이터 모델 · Parquet 정규화 존 · FDW 소비 | 사용자 결정: 파일이 인터페이스, DB는 외부 테이블(FDW)로 연결만 |
| v0.4 | 메달리온 존 네이밍(bronze/silver/gold 예약) · contrail 다중 제공자(adsb.lol/OpenSky) | 사용자 결정: 메달리온 관례 채택 + 다중 상류 소스 대응 실증 |
| v0.5 | 봉투 의미 반전: source=상류·kind=데이터셋 · 명령 25개를 상류 단위로 재편(usgs-feed, bbc, adsblol, yfinance, pykrx …) | 사용자 결정: 상류가 수집의 단위 — kind 접두사 편법 제거, 저장 프로토콜(봉투)로 통일 |
| v0.6 | RSS 단일 명령(`datalake-rss`) + 목록 파일(rss_feeds.toml) 관리. 사설·표준-준(準) 상류는 개별 명령 유지 | 사용자 결정: 표준 포맷은 클라이언트가 제네릭 — 대상 관리는 코드가 아닌 목록으로 |

## 10. 검증 상태 (2026-08-11)

- 테스트 56개 통과 (`mise run datalake:test`) — 독립성 AST 게이트,
  소스별 정규화의 hub 동형성, 멱등성(파티션 재작성·키 dedup), CLI 경로
- 실호출 스모크: quake·flashpoint·contrail CLI → bronze 적재 →
  `datalake-normalize`로 당일 파티션 11,680행 물질화
  (contrail_aircraft 5,217 · contrail_positions 6,121 ·
  flashpoint_events 305 · quake_events 37), pyarrow 직독으로 타입 보존 확인
- 미검증: trend(YT 키)·wake(전용 AIS 키)·market(extra 설치) 실호출 —
  키·환경 준비 후 동일 경로로 동작

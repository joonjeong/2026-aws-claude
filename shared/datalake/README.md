# datalake — 독립 원본 데이터레이크

hub의 6개 모듈이 보는 것과 동일한 외부 소스를 **hub와 완전히 독립적으로**
수집해 원본(raw) 그대로 디렉토리 레이크에 적재한다. hub는 정규화본만
남기고 원본을 버리며 fact는 7~30일 프루닝되지만, 레이크는 전 필드를 보존한다.

- 설계: `docs/specs/2026-08-11-datalake-design.md`
- 플랜: `docs/plans/2026-08-11-datalake.md`

## 독립성 계약

- `hub.*`/`app.*` import 금지 — `tests/test_independence.py`가 AST 검사로 강제
- hub의 `lab.db`를 알지도, 건드리지도 않음. 공유 코드는 라이브러리 `labkit`뿐
- 별도 프로세스: hub가 내려가도 수집은 계속, 레이크 장애도 hub에 전파 안 됨

## 실행

```bash
mise run datalake:run          # 상시 수집 (주기는 hub와 동일)
mise run datalake:once         # 1회 수집 스모크 (poll 소스만)
mise run datalake:test         # 테스트

# 직접 실행
cd shared/datalake
uv sync                        # market 소스까지 쓰려면: uv sync --extra market
uv run python -m datalake run --sources quake,news [--once]
uv run python -m datalake rebuild   # raw → SQLite 재구축 (멱등)
```

## 저장 구조

```
data/                                  # DATALAKE_ROOT (gitignore)
├── raw/<source>/<kind>/dt=YYYY-MM-DD/part-HH.jsonl[.gz]
│     한 줄 = {"fetched_at","source","kind","meta","payload(원본)"}
└── datalake.db                        # DATALAKE_SQLITE=1일 때만 (파생 존)
```

raw 존이 진실의 원천(source of truth). SQLite는 hub와 동형 스키마
(quake_events, news_articles, trend dim/fact, contrail/wake dim/fact,
market snapshots)의 조회 편의용 파생 존이며, `rebuild`로 언제든 재구축된다.

## 소스와 주기 (hub 기본값과 동일)

| 소스 | 방식 | 주기 | 활성 조건 |
|---|---|---|---|
| quake | USGS GeoJSON 폴링 | 60s | 항상 |
| news | RSS 15매체 폴링 | 매체당 120s | 항상 |
| trend | YouTube mostPopular(KR) | 60s | `YT_API_KEY` |
| contrail | adsb.lol re-api | 전세계 600s + 프리셋 4개 60s (순차 1.1s 간격) | 항상 |
| wake | AISStream WebSocket | 상시 스트림, 플러시 10s | `DATALAKE_AIS_KEY` |
| market | yfinance·pykrx | 30s 틱 + 장중 45s/장외 600s 게이트 | `--extra market` 설치 |

## env

| 변수 | 기본 | 설명 |
|---|---|---|
| `DATALAKE_ROOT` | `shared/datalake/data` | 레이크 루트 |
| `DATALAKE_SQLITE` | `0` | `1`이면 SQLite 파생 존 활성 |
| `DATALAKE_DB_PATH` | `<ROOT>/datalake.db` | SQLite 경로 |
| `DATALAKE_FLUSH_S` | `10` | 스트림 버퍼 플러시 주기 |
| `DATALAKE_COMPRESS` | `1` | 전일 파티션 gzip (일 1회) |
| `DATALAKE_RAW_RETENTION_DAYS` | `0` (무제한) | raw 보존기간 |
| `DATALAKE_*_INTERVAL_S` 등 | hub와 동일 | 소스별 주기 오버라이드 |
| `YT_API_KEY` | — | trend (hub와 **공유**) |
| `DATALAKE_AIS_KEY` | — | wake (hub와 공유 **금지**) |

## 운영 주의 (설계 §7)

1. **AISStream**: 키당 동시 연결 제한 — hub의 `WAKE_AIS_KEY`를 재사용하지 말고
   전용 키를 발급할 것. 미설정 시 wake만 비활성.
2. **YouTube 쿼터**: hub와 같은 키 사용 시 합산 ≈ 2,880유닛/일 (기본 쿼터
   10,000 내). 키를 분리하면 이 걱정도 없음.
3. **yfinance/pykrx**: 비공식 라이브러리 — 장시간 게이트가 실효 호출량을
   hub와 동일하게 유지한다. `DATALAKE_MARKET_INTERVAL_S`를 줄여도 게이트가
   지배하므로 안전.
4. **디스크**: contrail 전세계 원본이 지배적(일 300~400MB, gzip 후 ~40MB).
   로컬에서는 `--sources`로 필요한 소스만 돌리는 것을 권장.

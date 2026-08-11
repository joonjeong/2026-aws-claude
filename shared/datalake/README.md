# datalake — 독립 원본 데이터레이크

hub의 7개 모듈이 보는 것과 동일한 외부 소스를 **hub와 완전히 독립적으로**
수집해 원본(raw) 그대로 디렉토리 레이크에 적재한다. hub는 정규화본만
남기고 원본을 버리며 fact는 7~30일 프루닝되지만, 레이크는 전 필드를 보존한다.

- 설계: `docs/specs/2026-08-11-datalake-design.md`
- 플랜: `docs/plans/2026-08-11-datalake.md`

## 구조 원칙 (v0.2)

- **완전 독립**: `hub.*`/`app.*`/`labkit` import 금지 —
  `tests/test_independence.py`가 AST 검사로 강제. 의존성은
  httpx·feedparser·websockets뿐. hub의 `lab.db`를 알지도 않는다.
- **소스별 순수 클라이언트** (`datalake/sources/`): fetch/normalize만 —
  저장·경로·스케줄을 모른다. 향후 통합 솔루션이 그대로 import 가능.
- **소스별 one-shot CLI** (`datalake/cli/`): 클라이언트를 래핑해
  1회 수집→적재 후 종료. `uv run datalake-<source>`로 독립 실행.
- **스케줄링 없음**: 케이던스·재시도·백오프는 외부 오케스트레이터
  (Temporal 도입 예정) 소유. 아래 권장 스케줄은 문서일 뿐이다.
  실패는 간결한 로그 + 종료 코드로 전달 (0 성공 / 1 실패 / 2 소스 비활성).

## 명령과 권장 스케줄 (hub 기본값과 동일)

| 명령 | 소스 | 권장 스케줄 | 활성 조건 |
|---|---|---|---|
| `uv run datalake-quake` | USGS GeoJSON | 60s | 항상 |
| `uv run datalake-news [--feeds bbc,yna]` | RSS 15매체 | 120s | 항상 |
| `uv run datalake-trend` | YouTube mostPopular(KR) | 60s | `YT_API_KEY` |
| `uv run datalake-contrail --scope regions` | adsb.lol 프리셋 4개 (순차 1.1s) | 60s | 항상 |
| `uv run datalake-contrail --scope global` | adsb.lol 전세계 | 600s | 항상 |
| `uv run datalake-wake --duration 300` | AISStream 스트림 | 상시 또는 겹치지 않는 구간 실행 | `DATALAKE_AIS_KEY` |
| `uv run datalake-market` | yfinance·pykrx | 장중 45s / 장외 600s | `uv sync --extra market` |
| `uv run datalake-flashpoint` | GDELT 15분 export | 900s (파일 중복은 상태 파일로 스킵) | 항상 |
| `uv run datalake-rebuild` | raw → SQLite 재구축 (멱등) | 필요 시 | — |
| `uv run datalake-maintenance` | 전일 파티션 gzip + 보존 프루닝 | 일 1회 | — |

```bash
cd shared/datalake && uv sync        # 준비 (market까지: uv sync --extra market)
mise run datalake:smoke              # 무키 소스 스모크
mise run datalake:test               # 테스트
```

## 저장 구조

```
data/                                  # DATALAKE_ROOT (gitignore)
├── raw/<source>/<kind>/dt=YYYY-MM-DD/part-HH.jsonl[.gz]
│     한 줄 = {"fetched_at","source","kind","meta","payload(원본)"}
├── state/                             # one-shot 실행 간 소량 상태 (flashpoint last_url)
└── datalake.db                        # --sqlite 또는 DATALAKE_SQLITE=1일 때만
```

raw 존이 진실의 원천(source of truth). SQLite는 hub와 동형 스키마
(quake_events, news_articles, trend dim/fact, contrail/wake dim/fact,
flashpoint_events, market snapshots)의 조회 편의용 파생 존이며, 전 INSERT가
멱등이라 `datalake-rebuild`로 언제든 재구축된다.

flashpoint raw는 **CAMEO 루트 필터 전 CSV 전문**을 보존한다 — hub는 루트
14~20만 남기고 버리지만, 레이크에는 전 이벤트가 남고 SQLite 파생 존에서만
hub 동형 필터가 적용된다.

## env

| 변수 | 기본 | 설명 |
|---|---|---|
| `DATALAKE_ROOT` | `shared/datalake/data` | 레이크 루트 |
| `DATALAKE_SQLITE` | `0` | `1`이면 SQLite 파생 존 활성 (CLI `--sqlite`와 동일) |
| `DATALAKE_DB_PATH` | `<ROOT>/datalake.db` | SQLite 경로 |
| `DATALAKE_FLUSH_S` | `10` | wake 스트림 버퍼 플러시 주기 |
| `DATALAKE_COMPRESS` | `1` | maintenance의 전일 파티션 gzip |
| `DATALAKE_RAW_RETENTION_DAYS` | `0` (무제한) | maintenance의 raw 보존기간 |
| `DATALAKE_WAKE_PRESET` | `kr` | wake 관심 해역 (kr/taiwan/sea) |
| `YT_API_KEY` | — | trend (hub와 **공유**) |
| `DATALAKE_AIS_KEY` | — | wake (hub와 공유 **금지**) |

## 운영 주의 (설계 §7)

1. **AISStream**: 키당 동시 연결 제한 — hub의 `WAKE_AIS_KEY`를 재사용하지 말고
   전용 키를 발급할 것. 미설정 시 wake만 종료 코드 2로 비활성.
2. **YouTube 쿼터**: hub와 같은 키 사용 시 합산 ≈ 2,880유닛/일 (기본 쿼터
   10,000 내). 키를 분리하면 이 걱정도 없음.
3. **yfinance/pykrx**: 비공식 라이브러리 — 위 권장 스케줄(장중 45s/장외 600s)을
   Temporal 스케줄로 지켜서 hub와 합산 호출량을 관리할 것.
4. **adsb.lol**: 프리셋 조회는 클라이언트가 내부에서 순차 1.1s 간격을 지킨다
   (병렬 4요청 → 420 실측). 스케줄을 60s 미만으로 줄이지 말 것.
5. **flashpoint 404**: GDELT가 lastupdate.txt를 먼저 갱신하고 zip 게시가
   늦는 경우가 있다 — 종료 코드 1로 끝나며 다음 스케줄 실행이 곧 재시도다.
6. **디스크**: contrail 전세계 원본이 지배적(일 300~400MB, gzip 후 ~40MB).
   `datalake-maintenance`를 일 1회 스케줄에 포함할 것.

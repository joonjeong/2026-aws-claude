# datalake — 독립 원본 데이터레이크

hub의 7개 모듈이 보는 것과 동일한 외부 원천을 **hub와 완전히 독립적으로**
수집해 메달리온 레이크(landing·bronze)에 적재한다. hub는 정규화본만 남기고
원본을 버리며 fact는 7~30일 프루닝되지만, 레이크는 전 필드를 보존한다.

- 설계: `docs/specs/2026-08-11-datalake-design.md`
- 개요: `docs/datalake.md` (결정 이력 v0.1→v0.9)

## 구조 (v0.9) — 원천당 자기완결 파일 하나

```
datalake/
├── usgs_feed.py    ─┐
├── rss.py           │  파일 하나 = fetch → 순수 파싱(map/filter) →
├── youtube.py       │  landing(원본 봉투) + bronze(파싱 행) 랜딩까지
├── adsblol.py       ├  자기완결. 파일 간 import 없음
├── opensky.py       │  (test_independence.py가 hub/labkit 금지와 함께
├── aisstream.py     │   패키지 내부 상호 import도 검사)
├── yfinance.py      │
├── pykrx.py         │
├── gdelt.py        ─┘
├── maintenance.py      landing·bronze 전일 gzip + 보존 프루닝
├── rss_feeds.toml      RSS 수집 대상 목록 (env DATALAKE_RSS_FEEDS로 교체)
└── market_symbols.toml market 심볼·지수·지표 목록 (env DATALAKE_MARKET_SYMBOLS)
```

각 파일은 데이터가 유입되어 가공되는 순서대로 읽힌다:
**순수 파싱 함수들**(map/filter — 비정상은 None→필터) → **랜딩 함수**(append)
→ **collect**(IO 오케스트레이션) → **main**(argparse).

```
uv run datalake-<원천> [--output <root>]
   │ fetch 1회
   ├─▶ landing/<source>/<kind>/dt=…/part-HH.jsonl   원본 봉투 (불변, 진실의 원천)
   └─▶ bronze/<table>/dt=…/part-HH.jsonl            파싱·타입화 행 append (중복 허용)
```

- **봉투 의미론**: `source`=원천(usgs_feed, bbc, adsblol …),
  `kind`=데이터셋(quake, news, contrail_region_kr …). 한 원천이 여러
  kind를 생산할 수 있다 (adsblol → contrail 5개).
- **존 의미**: landing=원본 바이트 · bronze=무가공 파싱 레코드(1:1, append).
  **bronze→silver→gold는 정리된 원천을 기반으로 추후 재설계** — 현재
  리빌드성 명령(구 datalake-silver/bronze)은 두지 않는다.
- 스케줄링·재시도 없음 — 외부 스케줄러 소유.
  종료 코드: 0 성공 / 1 실패 / 2 원천 비활성(키 부재).
- `_state/`: 수집 상태 (gdelt last_url, opensky 토큰 — 0600).

## 명령과 권장 스케줄 (수집 주기는 hub 기본값과 동일)

| 명령 (`uv run …`) | 생산 (landing kind / bronze table) | 권장 스케줄 | 활성 조건 |
|---|---|---|---|
| `datalake-usgs-feed` | quake / quake_events | 60s | 항상 |
| `datalake-rss [--feeds bbc,yna] [--list]` | news / news_articles (매체 15) | 120s | 항상 |
| `datalake-youtube` | trend / trend_videos·trend_video_stats | 60s | `YT_API_KEY` |
| `datalake-adsblol --scope regions\|global` | contrail_* / contrail_aircraft·positions | 60s / 600s | 항상 |
| `datalake-opensky --scope …` | 동일 (bronze 테이블 수렴 — 제공자 중립) | 동일 | 항상 (인증 권장) |
| `datalake-aisstream --duration 300` | wake / wake_vessels·wake_positions | 상시 또는 겹침 없는 구간 | `DATALAKE_AIS_KEY` |
| `datalake-yfinance [--kinds …]` | market_overview·quotes_us / market_quotes | 장중 45s / 장외 600s | 항상 |
| `datalake-pykrx` | market_quotes_kr / market_quotes | 장중 45s / 장외 600s | 항상 |
| `datalake-gdelt [--force]` | flashpoint / flashpoint_events (CAMEO 14~20) | 900s | 항상 |
| `datalake-maintenance` | 전일 gzip + 보존 프루닝 | 일 1회 | — |

```bash
cd shared/datalake && uv sync
mise run datalake:smoke              # 무키 원천 스모크
mise run datalake:test               # 테스트

# 즉석 조회 (DuckDB) — bronze는 파싱된 행이라 바로 분석 가능
# SELECT * FROM read_json_auto('data/bronze/quake_events/*/*.jsonl');
```

## env

| 변수 | 기본 | 설명 |
|---|---|---|
| `DATALAKE_ROOT` | `shared/datalake/data` | 레이크 루트 (`--output`이 우선) |
| `DATALAKE_FLUSH_S` | `10` | aisstream 버퍼 플러시 주기 |
| `DATALAKE_COMPRESS` | `1` | maintenance의 전일 파티션 gzip |
| `DATALAKE_RAW_RETENTION_DAYS` | `0` (무제한) | landing·bronze 보존기간 |
| `DATALAKE_RSS_FEEDS` | 내장 `rss_feeds.toml` | RSS 수집 대상 목록 파일 |
| `DATALAKE_MARKET_SYMBOLS` | 내장 `market_symbols.toml` | market 심볼 목록 파일 |
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
   hub와 합산 호출량 관리. pykrx의 "KRX 로그인 실패" 출력은 무해.
4. **adsb.lol**: 프리셋 조회는 내부 순차 1.1s 간격 준수 (병렬 4요청 → 420
   실측). 스케줄 60s 미만 금지. 원시 URL 조립 필수 (%2C·jv2= 는 400).
5. **OpenSky**: 데이터센터 IP 차단 실측 — 클라우드에서는 adsblol 사용.
6. **GDELT 404**: lastupdate.txt 갱신 후 zip 게시가 늦는 경우 존재 —
   코드 1 종료, 다음 스케줄 실행이 곧 재시도.
7. **mk RSS**: 2026-08-11 기준 전 UA 403 (상류 측 차단) — 매체 격리로
   나머지 무영향, 지속 시 목록 파일에서 피드 URL 교체.
8. **디스크**: adsblol 전세계 landing이 지배적(일 300~400MB, gzip 후 ~40MB).
   `datalake-maintenance` 일 1회 필수.

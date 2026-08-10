# Trend Radar — 유튜브 급상승 수집/분석 서비스 설계

- 날짜: 2026-08-10
- 상태: 승인됨
- 시간 제약: 2시간 (테스트 생략, curl·브라우저 검증)
- 원 스펙: docs/youtube.md · 공용 레이어: docs/specs/2026-08-10-shared-kit-design.md (labkit)

## 목적

YouTube Data API v3 급상승(mostPopular, KR) 30건을 주기 수집해 스냅샷으로 쌓고,
직전 스냅샷 대비 rank delta/NEW/이탈과 카테고리 점유율을 파생, 단일 :8000에서
카드 그리드 + 시계열 SVG + 한국어 LLM 브리핑을 제공한다.

## 확정된 결정

| 결정 | 선택 | 근거 |
|---|---|---|
| 공용 레이어 | labkit (PollingCollector, SnapshotRingBuffer, BucketCachedText) | 사용자 결정 — 통합 모니터링 솔루션 재사용 전제 |
| 폴러 실행 | FastAPI lifespan 내 asyncio 태스크 | earthquake 선례, 외부 스케줄러 불필요 |
| 스냅샷 버킷 | `time_bucket(POLL_INTERVAL_S)` | 같은 시각 버킷 1회 저장(멱등)이 스펙, DynamoDB sk와 동형 |
| 키 없음 검증 | `YT_FIXTURE` 환경변수로 픽스처 스냅샷 주입 가능 | 사용자 결정(키 없음) — 프론트·파생 로직을 키 없이 브라우저 검증 |
| 브리핑 캐시 | BucketCachedText(bucket=POLL_INTERVAL_S), key=mode | "같은 시각 버킷 동안 캐시"가 스펙 |
| 배포 | 없음 (로컬 :8000) | 스펙에 배포 Phase 없음 |

## 1. 구조

```
youtube/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI, lifespan 폴러, StaticFiles
│   │   ├── config.py          # 주기(워크샵 60s/원작 3600s), 상수, 8개 고정 카테고리
│   │   ├── collector/youtube.py
│   │   ├── store/snapshots.py # labkit.SnapshotRingBuffer(48) 래핑
│   │   ├── derive/trends.py
│   │   ├── api/routes.py
│   │   └── llm/brief.py
│   └── requirements.txt       # fastapi, uvicorn, httpx, ../../shared
└── frontend/index.html
```

## 2. 수집기 (collector/youtube.py) — labkit.PollingCollector

- `videos.list?chart=mostPopular&regionCode=KR&maxResults=30&part=snippet,statistics`
  httpx GET, 주기 config(`POLL_INTERVAL_S`, 워크샵 60초).
- `videoCategories?hl=ko` 기동 시 1회, 실패 시 config의 기본 카테고리명 사용.
- 정규화: {video_id, title, channel, category_id, thumbnail(16:9 medium),
  view_count/like_count(문자열 숫자 → int, 비정상 → 0), published_at}. 카드 한 장의
  비정상이 사이클을 죽이지 않도록 아이템별 try/except.
- 상류 에러 본문은 로그에만. 예외·API 응답에는 상태 코드만 (키/프로젝트 정보 노출 격리).
- `YT_API_KEY` 미설정: 폴러는 기동하되 매 사이클 실패 기록 → `/api/trending`은
  빈 목록 + 소스 상태로 응답 (degraded).
- `YT_FIXTURE=<json path>` 설정 시 API 대신 픽스처 파일을 스냅샷으로 로드 (검증용).

## 3. 스냅샷 스토어 — labkit.SnapshotRingBuffer(48)

- 스냅샷 = `{captured_at, items[≤30]}`, bucket = `time_bucket(POLL_INTERVAL_S)`.
- 같은 버킷 재저장은 put()이 거부(멱등). 원작 DynamoDB(pk=scope, sk=버킷,
  attribute_not_exists) 교체 전제로 put/latest/previous/window만 사용.

## 4. 파생 (derive/trends.py)

- 최신 vs 직전 스냅샷: video_id 기준 rank delta(▲n/▼n/0), NEW(직전에 없음),
  이탈 수(직전에 있고 최신에 없음).
- 카테고리 점유율: 30건 중 카테고리별 비율. 시계열용으로 window(N)의 각 스냅샷에
  대해 {bucket, 점유율 맵, 진입/이탈 수} 산출.

## 5. API 계약

| 엔드포인트 | 응답 |
|---|---|
| `GET /healthz` | `{"status":"ok","snapshots":n}` |
| `GET /api/trending[?category=id]` | `{"captured_at", "items":[{...30건, rank, delta, is_new, category_name}], "stats":{합산 조회수, 채널 수, 최다 카테고리, 이탈 수}, "collector": 상태}` |
| `GET /api/trends?hours=N` | `{"points":[{bucket_ts, shares:{카테고리:비율}, entered, exited}]}` |
| `POST /api/brief?mode=now\|daily` | `{"brief","cached","bucket"}` — now=현재 스냅샷 요약, daily=기준선 대비 비교 |

- 카테고리 필터는 8개 고정: Music/Gaming/Entertainment/News&Politics/Sports/
  Film&Animation/Science&Tech/Comedy (config에 id 매핑).

## 6. 브리핑 (llm/brief.py) — labkit.bedrock

- `converse(system, 최신 스냅샷/기준선 요약, maxTokens=800)`,
  BucketCachedText(key=mode)로 같은 시각 버킷 캐시.
- 내용: 주제 클러스터 3~4개와 왜 뜨는지, 카테고리 분포 흐름, 제작/시청 인사이트
  2~3줄, 한국어. 키 미설정 503 / 상류 오류 502 (labkit 오류 계약).

## 7. 화면 (frontend/index.html)

- CSS 변수 듀얼 테마: 시스템 기본 + 토글 + localStorage.
- 헤더(타이틀, 마지막 수집, 수동 새로고침, 테마 토글), 통계 바 4종,
  카테고리 칩 8개, 30장 카드 그리드(순위 배지, ▲▼ delta, NEW 마커, 16:9 썸네일,
  제목 2줄 말줄임, 채널, 조회수/좋아요 축약(만/억), 클릭 → 유튜브 새 탭),
  시계열 = 인라인 SVG 누적 막대(외부 라이브러리 없음), 브리핑 카드(now/daily 버튼).
- 화면은 우리 API만 호출. `POLL_INTERVAL_S` 주기 자동 재조회.

## 8. 키의 거처

- `YT_API_KEY`, `AWS_BEARER_TOKEN_BEDROCK` 환경변수로만. 코드/응답/로그 노출 금지.

## 9. 구현 순서와 검증 (키 없음 전제)

| Phase | 내용 | 검증 |
|---|---|---|
| 1 | 수집기 + 스냅샷 + trending API | `curl /healthz`; `YT_FIXTURE`로 기동 후 `curl /api/trending` 30건; 키·픽스처 없이 기동 시 빈 목록 + collector 실패 상태 |
| 2 | 카드 그리드 + 칩 + delta/NEW | 픽스처 2개 버킷 주입 → 브라우저에서 ▲▼/NEW 확인 |
| 3 | 시계열 API + SVG | `curl '/api/trends?hours=1'`, 브라우저 누적 막대 |
| 4 | 브리핑 + 캐시 | `curl -X POST '/api/brief?mode=now'` → 503(키 없음) 확인, 코드 경로는 캐시 포함 완성 |

## 범위 밖 (YAGNI)

- DynamoDB 실구현, 배포(IaC), 자동화 테스트, WebSocket 푸시, 8개 외 카테고리

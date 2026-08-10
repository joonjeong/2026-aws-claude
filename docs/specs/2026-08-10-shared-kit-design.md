# labkit — 공용 수집/스토어/LLM 레이어 설계

- 날짜: 2026-08-10
- 상태: 승인됨 (사용자 결정: 루트 shared 패키지)
- 소비자: earthquake(Quake Watch), newsroom(Newsroom Lens), youtube(Trend Radar),
  market(Market Desk), 그리고 이후의 **통합 마켓 영향도 모니터링 솔루션**

## 목적

네 캡스톤이 각자 다른 데이터(지진, 뉴스 RSS, 유튜브 급상승, 시세)를 수집하지만
구조 패턴은 동일하다. 이 패턴을 `claude-lab/shared/` 의 설치 가능한 패키지
`labkit`으로 추출해, 이후 통합 모니터링 솔루션이 각 수집기를 그대로 import 해
조합할 수 있게 한다.

## 공통 패턴 → 모듈 매핑

| 패턴 | 모듈 | 사용 프로젝트 |
|---|---|---|
| 주기 폴링 루프 (실패 격리, 소스별 last_success/last_error) | `labkit.poller.PollingCollector` | earthquake(60s), newsroom(120s×4소스), youtube(60s) |
| 멱등 키 딕셔너리 스토어 (상한 + 정렬키 기반 축출) | `labkit.stores.IdempotentStore` | earthquake(id, 500), newsroom(link, 소스별 50) |
| 스냅샷 링버퍼 (시각 버킷 멱등, DynamoDB 교체 가능 인터페이스) | `labkit.stores.SnapshotRingBuffer` | youtube(48개), 통합 솔루션 |
| TTL 캐시 + single-flight | `labkit.cache.TTLCache` | market(시세 45s/차트), 통합 솔루션 |
| 시간 버킷 계산 | `labkit.cache.time_bucket` | earthquake/newsroom(10분), youtube(스냅샷 버킷) |
| Bedrock Converse httpx 직접 REST + 버킷 캐시 + 오류 매핑 | `labkit.bedrock` | earthquake/newsroom/youtube (market은 스펙상 boto3 converse_stream — 미사용) |
| env 오버라이드 설정 헬퍼 | `labkit.config` | 전체 |

## 구조

```
shared/
├── pyproject.toml        # name="labkit", requires: httpx
└── labkit/
    ├── __init__.py
    ├── poller.py         # PollingCollector
    ├── stores.py         # IdempotentStore, SnapshotRingBuffer
    ├── cache.py          # TTLCache(single-flight), time_bucket
    ├── bedrock.py        # converse(), BedrockError, BucketCachedText
    └── config.py         # env_str / env_int / env_float
```

- 의존성은 httpx 하나. feedparser/yfinance 등 도메인 의존성은 각 프로젝트에.
- 각 프로젝트 requirements.txt 에 `../shared` 한 줄 (pip 경로 설치).
- Docker 빌드는 **리포 루트 컨텍스트**: `COPY shared/ ./shared/` 후 프로젝트 복사.

## 계약 요점

### PollingCollector
```python
PollingCollector(name, interval_s, fetch: async () -> Any,
                 on_result: (Any) -> None | None = None)
.start() -> asyncio.Task      # FastAPI lifespan에서 기동
.status  -> {"name", "last_success", "last_error", "cycles", "consecutive_failures"}
```
- fetch/on_result 예외는 로그 + status 기록 후 다음 사이클 계속 (사이클 격리).
- 소스별 격리가 필요하면 소스당 인스턴스 하나 (newsroom은 4개).

### IdempotentStore
```python
IdempotentStore(max_items, evict_key: (item) -> sortable)
.upsert(key, item) -> bool    # True면 신규 진입 (사이클별 NEW 집계용)
.values() / .get(key) / len()
```
- 상한 초과 시 evict_key 오름차순(오래된 것)부터 제거. asyncio 단일 루프 전제, 락 없음.

### SnapshotRingBuffer
```python
SnapshotRingBuffer(capacity)
.put(bucket: int, snapshot) -> bool   # 같은 bucket 재저장 거부(멱등) — DynamoDB
                                      # attribute_not_exists(pk) 조건부 쓰기와 동형
.latest() / .previous() / .window(n) / .all()
```
- 원작의 DynamoDB(pk=scope, sk=시각 버킷) 교체를 전제로 put/latest/previous/window만
  사용하는 인터페이스 규율을 지킨다.

### TTLCache
```python
await cache.get_or_fetch(key, ttl_s, fetch: async () -> Any)
```
- 만료 전 히트는 즉시 반환, 미스는 키별 asyncio.Lock으로 single-flight —
  같은 키 동시 요청은 상류를 한 번만 부른다.

### bedrock
```python
await converse(system, user_text, max_tokens,
               model="global.anthropic.claude-sonnet-4-6",
               region="ap-northeast-2", timeout_s=60) -> str
BedrockError(status_code, message)   # 키 미설정 → 503, 상류/타임아웃/파싱 → 502
BucketCachedText(bucket_s)           # (text, cached, bucket) — 같은 버킷이면 캐시 반환
```
- 상류 에러 본문은 **로그에만**, 예외 메시지에는 상태 코드만 (스펙: 정보 노출 격리).
- Authorization: `Bearer $AWS_BEARER_TOKEN_BEDROCK` (환경변수로만).

## 범위 밖 (YAGNI)

- 영속화 어댑터 실구현 (DynamoDB 등) — 인터페이스 규율만
- 재시도/백오프 정책 — 다음 사이클이 곧 재시도
- market의 boto3 converse_stream — 프로젝트 로컬 (스펙 명시)

## 검증

`python smoke.py` — 스토어/링버퍼/TTL single-flight/버킷 캐시/키 미설정 503 을
파이썬 한 파일로 확인. (프로젝트별 검증은 각 설계 문서의 Phase 표를 따름)

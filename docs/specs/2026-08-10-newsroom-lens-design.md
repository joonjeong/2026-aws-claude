# Newsroom Lens — 4개 매체 관점 비교 뉴스룸 설계

- 날짜: 2026-08-10
- 상태: 승인됨
- 시간 제약: 2시간 (테스트 생략, curl·브라우저 검증)
- 원 스펙: docs/newsroom.md · 공용 레이어: docs/specs/2026-08-10-shared-kit-design.md (labkit)

## 목적

BBC World / Guardian World / NHK World(영문) / 연합뉴스 국제의 공개 RSS를 수집해
4열 그리드로 보여주고, LLM "렌즈"로 공통 토픽별 매체 프레임 차이를 한국어로
비교하는 뉴스룸. 로컬 :8000 완결 + CDK 스택은 synth 검증까지.

## 확정된 결정

| 결정 | 선택 | 근거 |
|---|---|---|
| 공용 레이어 | labkit (소스당 PollingCollector 4개, 소스당 IdempotentStore, BucketCachedText) | 사용자 결정 |
| Phase 4 범위 | `cdk synth` 통과까지 | 사용자 결정 — earthquake 선례와 동일 |
| CDK 언어/구성 | Python, earthquake 스택과 동일 패턴 (CloudFront → prefix list SG + X-Origin-Verify ALB → Fargate, Secrets 주입, 퍼블릭 서브넷만, desired_count=1) | 선례 재사용, 컨텍스트 전환 최소화 |
| 소스 격리 | 소스당 PollingCollector 인스턴스 (120초) | "피드 하나가 실패해도 나머지 계속"이 스펙 — 태스크 분리가 가장 단순 |
| 렌즈 JSON 파싱 | 코드펜스 제거 후 json.loads, 실패 시 502 | LLM "JSON만" 출력 요구의 현실적 방어 |
| 렌즈 캐시 | BucketCachedText(600s) | "같은 10분 버킷 캐시"가 스펙 |

## 1. 구조

```
newsroom/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI, lifespan에서 폴러 4개 기동, StaticFiles
│   │   ├── config.py          # SOURCES 4건 {id, name, lang, rss_url}, 주기 120s
│   │   ├── collector/rss.py   # feedparser 파싱 + 정규화
│   │   ├── store/articles.py  # 소스별 IdempotentStore(50)
│   │   ├── api/routes.py
│   │   └── llm/lens.py
│   └── requirements.txt       # fastapi, uvicorn, httpx, feedparser, ../../shared
├── frontend/index.html
├── Dockerfile                 # 루트 컨텍스트 빌드 (shared/ COPY)
└── infra/                     # CDK Python (synth까지)
```

## 2. 소스 (config.py)

각 항목 `{id, name, lang, rss_url}` — **URL은 구현 시점에 공식 RSS 허브에서 curl로
확인해 채우고 주석에 확인일(2026-08-10)을 기록한다.** 1차 후보:

| id | 이름 | 후보 URL |
|---|---|---|
| bbc | BBC World | `http://feeds.bbci.co.uk/news/world/rss.xml` |
| guardian | The Guardian World | `https://www.theguardian.com/world/rss` |
| nhk | NHK World (영문) | NHK World 공식 허브에서 확인 (영문 뉴스 피드) |
| yna | 연합뉴스 국제 | `https://www.yna.co.kr/rss/international.xml` (허브에서 확인) |

## 3. 수집기 (collector/rss.py) — labkit.PollingCollector × 4

- feedparser로 파싱(응답은 httpx로 받아 bytes 전달), 120초 주기, 소스별 최신 15건.
- 정규화: `{source, title, link, published(UTC ISO), summary}` — summary는
  HTML 태그 제거 후 300자 절단. 항목별 try/except (부분 실패 격리).
- 소스별 last_success를 PollingCollector.status가 그대로 제공 → 소스 상태 바.

## 4. 스토어 (store/articles.py) — 소스별 labkit.IdempotentStore(50)

- 멱등 키 = link. 같은 기사 재등장 시 published만 갱신.
- 축출은 published 오래된 것부터 (evict_key).

## 5. API 계약

| 엔드포인트 | 응답 |
|---|---|
| `GET /healthz` | `{"status":"ok","articles":n}` |
| `GET /api/articles` | `{"sources":[{id,name,lang,last_fetch,count,articles:[최신순 15]}]}` |
| `POST /api/lens` | 아래 6의 JSON + `{"cached","bucket"}` |

## 6. 렌즈 (llm/lens.py) — 이 캡스톤의 심장

- labkit `converse(system, 4개 소스 최신 헤드라인+요약 묶음, maxTokens=1500)`.
- 시스템 프롬프트가 강제하는 출력(JSON만):

```json
{"clusters":[{"topic":"한국어 토픽명","summary":"공통 사실 2문장",
  "frames":{"bbc":"프레임 1문장","guardian":"...","nhk":"...","yna":"..."},
  "sources":{"bbc":[기사 인덱스],"guardian":[...]}}],
 "overview":"오늘의 미디어 지형 3문장"}
```

- 클러스터는 **2개 이상 매체가 다룬 공통 토픽만 3~5개**, 미보도 매체 frame은 "미보도".
- 모든 생성 텍스트 한국어, 기사 제목 원문은 화면에서 병기.
- 파싱: 응답에서 코드펜스/전후 텍스트 제거 후 json.loads, 실패 시 502.
- BucketCachedText(600s) 캐시. 키 미설정 503 / 상류 502 (labkit 계약).

## 7. 화면 (frontend/index.html)

- CSS 변수 듀얼 테마 (토글 + localStorage + prefers-color-scheme).
- 상단 소스 상태 바: 4개 매체 × (마지막 수집, 건수, 실패 시 경고색).
- 기본 뷰 = 4열 카드 그리드 (매체별 최신 헤드라인, 원문 링크 새 탭, 상대 시각).
- "렌즈" 버튼 → 클러스터 뷰: 토픽 카드마다 공통 요약 + 4개 매체 프레임 나란히,
  "미보도" 회색 처리, 근거 기사 링크 칩(sources 인덱스 → 기사 link). 뷰 전환 토글.
- 모든 카드에 원문 출처 링크 필수.

## 8. 키와 윤리

- `AWS_BEARER_TOKEN_BEDROCK` 환경변수로만. 기사 본문 저장 안 함
  (헤드라인+요약+링크만), 출처 링크 상시 노출.

## 9. 배포 (infra/, CDK Python — synth까지)

earthquake 스택과 동일 패턴의 단일 스택: VPC(2AZ 퍼블릭만) / Fargate(desired 1,
ALB SG만 인바운드) / ALB(CloudFront prefix list + X-Origin-Verify 리스너 규칙,
기본 403) / CloudFront(오리진 커스텀 헤더, Secrets Manager dynamic reference) /
Bearer는 ECS secrets 주입. 검증은 `cdk synth` 클린 통과.

## 10. 구현 순서와 검증 (Bedrock 키 없음 전제)

| Phase | 내용 | 검증 |
|---|---|---|
| 1 | 수집기 4개 + 스토어 + /api/articles | `curl /healthz`, `curl /api/articles` — 실제 RSS 4개 수집 확인 (키 불요) |
| 2 | 4열 그리드 + 소스 상태 바 | 브라우저 확인 |
| 3 | 렌즈 JSON + 클러스터 뷰 | `curl -X POST /api/lens` → 503(키 없음) 확인, 프론트는 오류 배너 |
| 4 | Dockerfile + CDK 스택 | `cdk synth` 클린 통과 |

## 범위 밖 (YAGNI)

- 기사 본문 수집/저장, 번역 저장, DB 영속화, 실배포(deploy), 자동화 테스트

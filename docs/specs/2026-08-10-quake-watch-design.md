# Quake Watch — 전 세계 실시간 지진 모니터 설계

- 날짜: 2026-08-10
- 상태: 승인됨
- 시간 제약: 2시간 (테스트 생략, curl·브라우저 검증)

## 목적

USGS 실시간 지진 피드를 60초 주기로 수집해, 단일 :8000 서비스에서 세계지도 시각화 +
통계 + 한국어 LLM 브리핑을 제공하는 웹 앱. 로컬 실행이 1차 목표, CDK로 AWS 배포
코드까지 준비(synth 검증, 실배포는 이후 `cdk deploy` 한 줄).

## 확정된 결정

| 결정 | 선택 | 근거 |
|---|---|---|
| CDK 언어 | Python | 백엔드와 동일 언어·가상환경, 2시간 제약에서 컨텍스트 전환 최소화 |
| Phase 4 범위 | `cdk synth` 검증까지 | 실배포는 비용·자격증명 필요, 배포는 이후 한 줄로 실행 가능 |
| 폴러 실행 방식 | FastAPI lifespan 내 asyncio 태스크 | 인메모리 스토어와 같은 프로세스 공유, 외부 스케줄러 불필요 |
| 규모 필터 | 클라이언트 사이드 | 슬라이더 반응 즉각, 서버 왕복 없음 (서버 필터도 API 계약상 지원) |
| X-Origin-Verify 검사 위치 | ALB 리스너 규칙 | 앱 코드가 헤더를 몰라도 됨, 로컬 개발 시 그대로 동작 |
| VPC 구성 | 퍼블릭 서브넷만 (NAT 없음) | Fargate 태스크 퍼블릭 IP + SG 제한, NAT 월 ~$65 절약 |
| Fargate desired_count | 1 고정 | 인메모리 스토어·폴러 구조상 다중 태스크는 각자 폴링하게 됨 |

## 1. 구조

```
earthquake/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI 앱, lifespan 폴러 기동, 정적 파일 마운트
│   │   ├── config.py        # USGS URL, 폴링 주기, 스토어 상한, Bedrock 설정 (env 오버라이드)
│   │   ├── collector/usgs.py
│   │   ├── store/quakes.py
│   │   ├── api/routes.py
│   │   └── llm/brief.py
│   └── requirements.txt     # fastapi, uvicorn, httpx
├── frontend/index.html      # 빌드 없는 단일 정적 SPA
├── Dockerfile               # python:3.11-slim 단일 스테이지
└── infra/                   # CDK Python 앱 (app.py + 단일 스택)
```

FastAPI가 `frontend/`를 StaticFiles로 루트에 마운트해 :8000 하나로 완결.

## 2. 수집기 (collector/usgs.py)

- `httpx.AsyncClient`(timeout 10초)로 60초마다
  `https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson` GET.
- 요청 실패(네트워크, 비200, JSON 파싱) 시 로그만 남기고 다음 사이클 계속.
- feature별 정규화를 try/except로 격리 — 한 건의 비정상이 나머지를 죽이지 않음.
- 정규화 스키마: `id`, `mag`(float, 비정상→0), `place`(str, 비정상→"unknown"),
  `time`(UTC ms int, 비정상→0), `lon`/`lat`/`depth_km`(float, 비정상→0).

## 3. 스토어 (store/quakes.py)

- `dict[id → event]` 인메모리, 최대 500건.
- upsert만 존재: 같은 id는 갱신, 중복 삽입 없음 (id가 멱등 키).
- 500건 초과 시 이벤트 시각(`time`) 기준 오래된 것부터 제거.
- 사이클마다 신규 진입 id 목록 기록, `last_fetch`(수집 성공 시각) 갱신.
- asyncio 단일 이벤트 루프 전제이므로 락 없음.

## 4. API 계약 (api/routes.py)

| 엔드포인트 | 응답 |
|---|---|
| `GET /healthz` | `{"status":"ok","events":<보유 건수>}` |
| `GET /api/quakes?hours=24&min_mag=2.5` | `{"events":[최신순 목록], "stats":{"count","max_mag","top_region","last_fetch"}}` |
| `POST /api/brief` | `{"brief":"지난 24시간, 지구는 …","cached":bool,"bucket":int}` |

- `hours`(기본 24)와 `min_mag`(기본 2.5)로 시간 창·규모 필터.
- `top_region`: place 문자열의 마지막 콤마 뒤 토큰으로 집계
  ("10km SW of Adak, Alaska" → "Alaska"). 콤마 없으면 place 전체.

## 5. 화면 (frontend/index.html)

- **테마**: CSS 변수 기반 라이트/다크, 토글 + localStorage, 초기값 `prefers-color-scheme`.
- **통계 바**: 24h 건수 · 최대 규모 · 최다 지역 · 마지막 수집 시각(KST).
- **지도**: `viewBox="0 0 1000 500"` 인라인 SVG, 외부 라이브러리 없음.
  - 대륙 윤곽: 간이 폴리라인 하드코딩 (대륙 실루엣 수준).
  - 진앙 원: `r = mag * 2.2`px.
  - 색: 깊이 0km 주황(#ff8c42) → 300km+ 보라(#7c3aed) 선형 보간.
  - 최근 1시간 이벤트: CSS @keyframes 펄스 링.
  - 좌표 변환: `x=(경도+180)/360*폭`, `y=(90-위도)/180*높이`.
- **테이블**: 최근 이벤트 — 시각(KST 변환), 규모, 지역, 깊이.
- **슬라이더**: 규모 필터 2.5~6.0, 클라이언트 필터로 지도·테이블·통계 동시 반영.
- 60초마다 `/api/quakes` 재조회.

## 6. 브리핑 (llm/brief.py)

- httpx로 직접 REST (SDK 없음):
  `POST https://bedrock-runtime.ap-northeast-2.amazonaws.com/model/global.anthropic.claude-sonnet-4-6/converse`
- 헤더: `Authorization: Bearer $AWS_BEARER_TOKEN_BEDROCK`, `Content-Type: application/json`.
- `inferenceConfig.maxTokens: 700`.
- 입력: 24h 요약 통계 + 규모순 상위 10개 이벤트.
- 시스템 프롬프트: "지난 24시간, 지구는"으로 시작하는 한국어 브리핑 —
  전체 흐름 한 문단 → 주목 이벤트 2~3개 해설 → 활동 급증 지역.
- 캐시: `bucket = int(time.time() // 600)` — 같은 10분 버킷이면 저장 텍스트 즉시 반환.
- 오류 처리: 토큰 미설정 → 503 + 안내, Bedrock 오류 → 502로 원인 전달.

## 7. 키의 거처

- `AWS_BEARER_TOKEN_BEDROCK`은 환경변수로만 존재. 코드·이미지·리포지토리에 없음.
- USGS는 키 불필요. 프론트엔드는 우리 API만 호출 (Bedrock 직접 호출 없음).

## 8. 배포 (infra/, CDK Python — synth까지)

단일 스택:

- **VPC**: 2AZ, 퍼블릭 서브넷만 (NAT 없음).
- **ECS Fargate**: 퍼블릭 IP 부여, SG는 ALB SG에서만 인바운드 허용, `desired_count=1`.
- **ALB**: SG 인바운드를 CloudFront origin-facing 관리형 프리픽스 리스트로 제한.
  리스너 기본 액션 403 고정 응답, `X-Origin-Verify` 헤더 일치 시에만 포워드.
- **CloudFront**: ALB를 HTTP 오리진으로 (도메인/ACM 없이 개장),
  오리진 커스텀 헤더로 `X-Origin-Verify` 주입. 값은 Secrets Manager 자동 생성
  시크릿 하나를 CloudFront 오리진 헤더와 ALB 리스너 규칙 양쪽에서 참조
  (CloudFormation dynamic reference) — 코드·템플릿에 평문 없음.
- **Secrets Manager**: Bearer 토큰을 ECS secrets로 컨테이너 환경변수 주입.
  시크릿 값 자체는 배포 전 수동 등록 (CDK 코드에 값 없음).
- 검증: `cdk synth` 클린 통과.

## 9. 구현 순서와 검증

| Phase | 내용 | 검증 |
|---|---|---|
| 1 | 수집기 + 스토어 + `/api/quakes` | `curl /healthz`, `curl '/api/quakes?hours=24&min_mag=4'` |
| 2 | 지도 SVG + 테이블 + 필터 + 테마 | 브라우저 확인 |
| 3 | 브리핑 + 10분 캐시 | `curl -X POST /api/brief` 2회 — 두 번째 `cached:true` |
| 4 | CDK 스택 | `cdk synth` 클린 통과 |

## 범위 밖 (YAGNI)

- 자동화 테스트 (시간 제약, 스펙 명시)
- WebSocket/SSE 푸시 — 60초 폴링으로 충분
- DB 영속화 — 인메모리 500건이 계약
- 다중 태스크 스케일링, 커스텀 도메인/ACM, WAF

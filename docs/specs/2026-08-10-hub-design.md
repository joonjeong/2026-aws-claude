# Hub — 4개 캡스톤 통합 서비스 설계

- 날짜: 2026-08-10
- 상태: 승인됨 (사용자 결정: 단일 서비스 통합, API 첫 네임스페이스 구분, 진입점에서 선택)
- 선행 문서: specs/2026-08-10-shared-kit-design.md(labkit) + 각 프로젝트 설계 문서 4건
- **프론트엔드는 원 스펙(docs/*.md)의 화면 절이 원본 계약** — 이 문서 §6의
  체크리스트는 그 원문을 모듈별로 옮겨 적은 것이며, 구현은 체크리스트 전 항목을 충족해야 한다.

## 목적

4개 캡스톤(quake/news/trend/market)을 **하나의 FastAPI 서비스**로 합친다.
백엔드는 `/api/{모듈}` 첫 네임스페이스로 구분, 프론트엔드는 첫 진입점(런처)에서
모듈을 선택해 각 앱으로 이동한다. 각 앱 화면은 원 스펙의 요구를 그대로 구현한다.

## 확정된 결정

| 결정 | 선택 | 근거 |
|---|---|---|
| 배치 | `hub/` 신설, 기존 youtube/newsroom/market 코드는 mv 이관 후 잔여 정리 | 사용자 결정 (백업 없이 이동 — mv라 파일 보존) |
| quake | 이번에 신규 구현해 포함 | 사용자 결정 — USGS는 키 불요, 라이브 검증 가능 |
| 모듈 선택성 | `ENABLED_MODULES` env(기본 전체) + 런처는 활성 모듈만 노출 | "하나의 서비스에서 선택적으로 반영" |
| 프론트 통합 방식 | 런처(/) + 모듈별 서브패스 서빙 — 3개는 원 스펙대로 빌드 없는 정적 SPA 한 장, market만 Vite 빌드(base=/market/) | 원 스펙의 프론트 성격을 훼손하지 않는 유일한 통합 |
| IaC | newsroom의 infra/를 hub/infra로 이관 (단일 서비스 = 단일 스택), synth까지 | 기존 결정 유지 |
| earthquake/ 디렉토리 | 손대지 않음 (자체 .git 보유, 코드 없음) | git 저장소 임의 삭제 회피 — 설계 문서는 docs/specs에 이미 집결 |

## 1. 구조

```
hub/
├── backend/
│   ├── requirements.txt      # fastapi uvicorn[standard] httpx feedparser yfinance pykrx boto3 + -e ../../shared
│   ├── static/market/        # market 프론트 빌드 산출물
│   └── app/
│       ├── main.py           # 모듈 로더·조합기 (아래 §2 계약)
│       ├── config.py         # ENABLED_MODULES (기본 quake,news,trend,market)
│       └── modules/
│           ├── quake/        # collector/store/api/llm/config (설계: quake-watch 문서)
│           ├── news/         # ← newsroom/backend/app 이관
│           ├── trend/        # ← youtube/backend/app 이관
│           └── market/       # ← market/backend/app 이관
├── frontend/
│   ├── hub/index.html        # 런처 (첫 진입점)
│   ├── quake/index.html
│   ├── news/index.html
│   ├── trend/index.html
│   └── market/               # ← market/frontend 이관 (Vite, base '/market/')
├── fixtures/trending.json    # ← youtube/fixtures 이관 (trend 검증용)
├── infra/                    # ← newsroom/infra 이관 (hub 스택으로 개명, synth까지)
└── Dockerfile                # 멀티스테이지: node로 market 빌드 → python:3.11-slim
```

## 2. 모듈 계약 (backend/app/modules/&lt;id&gt;/__init__.py)

각 모듈은 다음 4개를 노출한다. **main.py는 이 계약만 안다.**

```python
META: dict            # {"id","title","tagline","icon"} — 런처 카드용
router: APIRouter     # /api/<id> 프리픽스 없이 상대 경로만 정의 (예: /quakes, /brief)
async def startup()   # lifespan 기동 (수집기 start 등)
async def shutdown()  # lifespan 종료 (수집기 stop 등)
def health() -> dict  # 모듈 상태 (수집기 status, 보유 건수 등)
```

main.py 동작: ENABLED_MODULES의 각 모듈을 import →
`include_router(prefix=f"/api/{id}")` → lifespan에서 startup/shutdown 일괄 →
`GET /healthz`(모듈별 health 집계), `GET /api/modules`(런처 데이터) →
정적 마운트: `/quake` `/news` `/trend`(frontend/), `/market`(static/market 빌드),
마지막에 `/` = frontend/hub(런처). 모듈 import 실패는 로그 후 해당 모듈만 제외.

## 3. API 네임스페이스 매핑 (기존 계약 → hub)

| 모듈 | 기존 | hub |
|---|---|---|
| quake | /api/quakes, /api/brief | /api/quake/quakes, /api/quake/brief |
| news | /api/articles, /api/lens | /api/news/articles, /api/news/lens |
| trend | /api/trending, /api/trends, /api/brief | /api/trend/trending, /api/trend/trends, /api/trend/brief |
| market | /api/market/*, /api/stocks/*, /api/ai/stocks/* | /api/market/overview·quotes, /api/market/stocks/*, /api/market/ai/stocks/* |
| 공통 | /healthz | /healthz(집계) + /api/{id}/healthz(모듈) |

쿼리 파라미터·응답 스키마·오류 계약(키 없음 503, 상류 502 상태코드만)은 전부 원 계약 유지.

## 4. 런처 (frontend/hub/index.html)

- 빌드 없는 정적 한 장, CSS 변수 듀얼 테마(시스템 + 토글 + localStorage).
- `/api/modules` + `/healthz`를 읽어 활성 모듈 카드를 렌더:
  아이콘, 타이틀, 태그라인, 상태 요약(수집 성공/실패·보유 건수), 클릭 → `/{id}/`.
- 비활성(미탑재) 모듈은 카드 자체가 나타나지 않는다.

## 5. 검증 포트 배정 (병렬 작업 규율)

각 모듈 작업자는 `ENABLED_MODULES=<자기 모듈>`로 단독 기동해 검증:
quake=8001, news=8002, market=8003, trend=8004. 통합 검증(전 모듈)은 8000.

## 6. 프론트엔드 요구 체크리스트 (원 스펙 원문 이관)

### quake (`/quake/`, 원문: docs/earthquake.md §5)
- [ ] 라이트/다크 듀얼 테마 (토글 + localStorage)
- [ ] 상단 통계 바: 24h 건수 · 최대 규모 · 최다 지역 · 마지막 수집 시각
- [ ] 등장방형(equirectangular) 세계지도 — **외부 라이브러리 없는 인라인 SVG**
- [ ] 대륙 윤곽: 간이 폴리라인 수준
- [ ] 진앙 원: 반지름 `mag * 2.2px`
- [ ] 색 = 깊이: 얕음 주황(#ff8c42) → 깊음 보라(#7c3aed) 보간
- [ ] 최근 1시간 이벤트 펄스 애니메이션
- [ ] 좌표 변환: `x=(경도+180)/360*폭`, `y=(90-위도)/180*높이`
- [ ] 하단 최근 이벤트 테이블: 시각(KST 변환) · 규모 · 지역 · 깊이
- [ ] 규모 필터 슬라이더 2.5~6.0 (지도·테이블·통계 동시 반영)
- [ ] 60초 주기 재조회

### news (`/news/`, 원문: docs/newsroom.md §7)
- [ ] 라이트/다크 듀얼 테마
- [ ] 상단 소스 상태 바: 4개 매체 × (마지막 수집, 건수)
- [ ] 기본 뷰 = 4열 카드 그리드: 매체별 최신 헤드라인, 원문 링크 새 탭, 상대 시각
- [ ] "렌즈" 버튼 → 클러스터 뷰: 토픽 카드마다 공통 요약 + 4개 매체 프레임 나란히
- [ ] 미보도 프레임 회색 처리
- [ ] 근거 기사 링크 칩 (sources 인덱스 → 기사 링크)
- [ ] 뷰 전환 토글 (그리드 ↔ 클러스터)
- [ ] 모든 카드에 원문 출처 링크 필수

### trend (`/trend/`, 원문: docs/youtube.md §7)
- [ ] 듀얼 테마: 시스템 기본 + 토글 + localStorage, 색은 CSS 변수
- [ ] 헤더: 타이틀, 마지막 수집 시각, 수동 새로고침, 테마 토글
- [ ] 통계 바: 합산 조회수 · 채널 수 · 최다 카테고리 · 이탈 수
- [ ] 카테고리 칩 8개
- [ ] 30장 카드 그리드: 순위 배지 + ▲▼ delta 배지 + NEW 마커, 16:9 썸네일,
      제목 2줄 말줄임, 채널, 조회수/좋아요 축약, 클릭 시 유튜브 새 탭
- [ ] 시계열: 최근 N시간 카테고리 점유율 누적 막대 — **외부 차트 라이브러리 없이 인라인 SVG**
- [ ] 브리핑 카드: now/daily 모드 버튼

### market (`/market/`, 원문: docs/market.md §5·6·8)
- [ ] Dashboard: 상단 경제지표 바, 지수 카드 5장(등락색), 종목 테이블
      (US/KR 탭, Symbol/Name/Price/Change/%/Volume, 상승 초록/하락 빨강)
- [ ] react-query 45초 자동 갱신
- [ ] StockDetail: 테이블 클릭 진입, StockHeader(현재가·등락률·거래량)
- [ ] lightweight-charts 캔들 + 1W/1M/3M/1Y 기간 탭
- [ ] ReturnsRow(기간 수익률 4종), Week52Bar(52주 범위 내 현재 위치)
- [ ] 뒤로 가기로 대시보드 복귀
- [ ] AIPanel: SSE 델타 누적 타자기 렌더, 스트리밍 중 phase 배지(fetching/analyzing),
      react-query 대신 fetch 직접, 키 없음 503 시 패널 비활성
- [ ] 무드: 다크 딥네이비, 숫자 우측 정렬, 상승 초록 ▲ / 하락 빨강 ▼

## 7. 이관 규칙

- 코드는 가능한 한 **mv로 이동** 후 import 경로만 수정 (`app.X` →
  `app.modules.<id>.X`). 각 모듈의 옛 main.py 로직(lifespan, 정적 마운트)은
  모듈 `__init__.py`의 startup/shutdown + hub main.py로 흡수되어 소멸.
- 프론트 API 경로를 §3 매핑으로 치환. market은 vite `base:'/market/'`,
  `outDir: ../../backend/static/market`.
- venv는 hub/backend/.venv 하나 (전 의존성 사전 설치, 작업자는 pip 실행 금지).
- 이관 후 잔여물(옛 .venv, 빈 디렉토리) 정리는 통합 검증 후 오케스트레이터가 수행.

## 8. 검증

| 단계 | 내용 | 방법 |
|---|---|---|
| 모듈 단독 | 자기 모듈만 활성으로 기동, 원 설계 문서의 Phase 검증 반복 (키 없음 변형) | curl, 배정 포트 |
| 프론트 | §6 체크리스트 전 항목 | 브라우저/curl + 코드 대조 |
| 통합 | 전 모듈 활성 :8000 — 런처, 4개 네임스페이스 API, 4개 프론트, /healthz 집계 | curl |
| IaC | hub/infra `cdk synth` 클린 | npx aws-cdk |

## 범위 밖 (YAGNI)

- 모듈 간 데이터 결합(마켓 영향도 상관관계) — 다음 단계의 통합 모니터링 솔루션
- 실배포, 자동화 테스트, 모듈 핫스왑

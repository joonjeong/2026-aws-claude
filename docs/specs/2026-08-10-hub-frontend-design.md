# Hub Frontend — 단일 앱 + 빌드 타임 앱 선택 설계

- 날짜: 2026-08-10
- 상태: 승인됨 (사용자 지시: "프론트엔드도 단일 앱으로, 빌드 옵션으로 앱 선택")
- 선행: specs/2026-08-10-hub-design.md — §6 화면 체크리스트는 여전히 수용 기준.
  이 문서는 hub 설계 문서의 "런처 + 모듈별 정적 SPA" 구조(§1·§4)를 대체한다.

## 목적

hub/frontend/ 전체를 **하나의 Vite + React + TS 앱**으로 만들고, 빌드 시
`VITE_APPS` 환경변수로 포함할 앱을 선택한다. 선택되지 않은 앱은 번들에서
완전히 제외된다(코드 스플리팅으로 로드만 안 하는 것이 아니라 빌드 자체에서 빠짐).
백엔드 `ENABLED_MODULES`(런타임 선택)의 프론트엔드 대응물(빌드 타임 선택).

## 확정된 결정

| 결정 | 선택 | 근거 |
|---|---|---|
| 앱 선택 메커니즘 | Vite 가상 모듈(`virtual:apps`) — 플러그인이 VITE_APPS로 선택된 앱만 import하는 레지스트리를 생성 | 정적 import 그래프에서 빠지므로 트리셰이킹이 아니라 **미포함**이 보장됨 |
| 라우팅 | 수제 pathname 라우터 (pushState + popstate) | 라우트 5개에 react-router 의존성 불요; market 내부는 기존 상태 기반 유지 |
| 코드 스플리팅 | 앱별 `React.lazy(() => import(...))` | 포함된 앱도 진입 시점에만 로드 |
| 테마 | 셸이 전역 소유 (data-theme + localStorage), 앱은 CSS 변수 소비 | 앱마다 토글 중복 제거; 원 스펙의 "듀얼 테마" 요구는 셸 차원에서 충족. market은 원 스펙대로 자체 다크 딥네이비 팔레트를 스코프 내 고정 |
| 스타일 격리 | 셸이 각 앱을 `.app-<id>` 루트로 감싸고, 앱 CSS는 전부 그 아래로 네임스페이스 | 4개 앱 CSS의 전역 충돌 방지 |
| react-query | 셸 루트에 QueryClientProvider 1개 | market이 사용, 타 앱은 무시해도 무해 |
| 서빙 | 빌드 산출물 `hub/backend/static/app/` → FastAPI가 /assets 정적 + 나머지 GET은 index.html 폴백 (api/ 프리픽스는 404) | `/quake` 딥링크 새로고침 지원 |
| 원 스펙 "빌드 없는 정적 SPA 한 장" | 이 지시로 폐기 | 사용자 지시가 원 스펙보다 우선 |

## 1. 구조

```
hub/frontend/
├── package.json          # react, react-dom, @tanstack/react-query, lightweight-charts, vite, ts
├── vite.config.ts        # appsPlugin(virtual:apps), base '/', outDir ../backend/static/app
├── tsconfig.json
├── index.html
└── src/
    ├── main.tsx           # 테마 초기화, QueryClientProvider, <App/>
    ├── App.tsx            # pathname 라우터: '/'→런처, '/<id>'→앱 (Suspense + .app-<id> 래퍼 + 셸 톱바)
    ├── index.css          # 리셋 + 전역 테마 CSS 변수 + 셸/런처 스타일
    ├── launcher/Launcher.tsx
    └── apps/
        ├── types.ts       # AppDef {id,title,tagline,icon,Component(lazy)}
        ├── virtual-apps.d.ts
        ├── quake/  index.ts + QuakeApp.tsx + quake.css
        ├── news/   index.ts + NewsApp.tsx + news.css
        ├── trend/  index.ts + TrendApp.tsx + trend.css
        └── market/ index.ts + MarketApp.tsx + … (기존 컴포넌트 이관)
```

## 2. 빌드 옵션

```bash
npm run build                              # 4개 앱 전부
VITE_APPS=quake,market npm run build       # 두 앱만 — news/trend 코드는 번들에 없음
```

- `vite.config.ts`의 appsPlugin이 `virtual:apps`를 아래처럼 생성:
  `import { app as quake } from '/src/apps/quake/index'; …; export const APPS=[quake,…]`
- 알 수 없는 id는 무시, 빈 목록이면 전체로 폴백하지 않고 런처만 있는 셸 빌드.
- Dockerfile은 `ARG APPS`로 같은 옵션 노출.

## 3. 셸 계약 (각 앱 모듈이 지켜야 할 것)

- `src/apps/<id>/index.ts`가 `export const app: AppDef` — Component는
  `lazy(() => import('./<Id>App'))`.
- 앱 컴포넌트는 자기 화면만 렌더 (html/head/전역 body 스타일 금지).
- 모든 CSS 선택자는 `.app-<id>` 하위로 네임스페이스.
- API는 기존 그대로 `/api/<id>/...` 절대 경로 fetch.
- 테마 토글을 직접 만들지 않는다 — 셸 톱바가 제공, `[data-theme]` CSS 변수 소비.
- hub 설계 문서 §6 자기 앱 체크리스트는 그대로 수용 기준
  (테마 토글 항목만 "셸 제공"으로 충족).

## 4. 백엔드 변경 (main.py)

- 모듈별 정적 마운트 제거 → `static/app/` 단일 SPA:
  실존 파일은 그대로, `api/`로 시작하지 않는 나머지 GET은 index.html 폴백(딥링크).
- `/api/modules`는 그대로 — 런처가 "빌드 포함 앱 ∩ 백엔드 활성 모듈"을 계산해
  양쪽 모두 켜진 앱만 활성 카드로, 빌드엔 있으나 백엔드 모듈이 꺼진 앱은
  비활성 카드로 표시.

## 5. 검증

| 항목 | 방법 |
|---|---|
| 전체 빌드 | `npm run build` 클린 → :8010 서빙, 런처·4앱·딥링크 새로고침 200 |
| 부분 빌드 | `VITE_APPS=quake,market npm run build` → dist에 news/trend 문자열 부재(grep), 런처 카드 2장 |
| API 회귀 | 통합 테스트 스크립트 재실행 (네임스페이스 API·503 계약 불변) |
| §6 체크리스트 | 앱별 코드 대조 (포팅 후에도 전 항목 유지) |

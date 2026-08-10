# Hub 사이드바 셸 개편 설계

날짜: 2026-08-10 · 상태: 승인됨 (A안)

## 목표

허브를 "여러 앱의 런처"에서 "여러 메뉴를 가진 하나의 시스템"으로 재구성한다.
왼쪽 고정 사이드바에서 모듈을 전환하고, 루트(`/`)는 시스템 홈 화면을 보여준다.

## 결정 사항

- **접근**: 셸 개편 (라우터 라이브러리 미도입 — 기존 `usePath` 히스토리 라우팅 유지)
- **루트(`/`) 동작**: 시스템 홈 화면 — 모듈 상태 요약 대시보드 (사용자 선택)
- **메뉴 순서**: Market Desk → Newsroom Lens → Trend Radar → Quake Watch → Laboratory

## 레이아웃

```
┌──────────┬──────────────────────────────┐
│ claude-  │                              │
│ lab      │   콘텐츠 영역 (독립 스크롤)      │
│──────────│   / → 홈 대시보드              │
│ 📊 Market│   /market 등 → 해당 앱         │
│ 📰 News  │   /lab → Laboratory 빈 상태    │
│ 📈 Trend │                              │
│ 🌋 Quake │                              │
│ 🧪 Lab   │                              │
│──────────│                              │
│ 테마 토글  │                              │
└──────────┴──────────────────────────────┘
```

- 사이드바 폭 약 220px 고정, 좁은 화면(<720px)에서 아이콘 전용 폭으로 축소
- 브랜드(`claude-lab`) 클릭 → 홈(`/`)
- 활성 메뉴 하이라이트, 백엔드 모듈 비활성 시 disabled (기존 런처 로직 재사용)
- 기존 상단 `shell-bar` 제거 — 뒤로가기·테마 역할이 사이드바로 이동

## 컴포넌트

| 파일 | 역할 |
|---|---|
| `src/App.tsx` | 셸 레이아웃 + 경로 → 콘텐츠 매핑 (홈 / 앱 / lab / 폴백=홈) |
| `src/shell/Sidebar.tsx` | 메뉴 목록, 활성/비활성 상태, 테마 토글 푸터 |
| `src/shell/Home.tsx` | 모듈 상태 카드 그리드 (`/api/modules`, `/healthz` 30초 폴링 재사용) |
| `src/shell/Laboratory.tsx` | 🧪 준비 중 빈 상태 |
| `src/shell/useModules.ts` | modules/health 쿼리 공용 훅 (Sidebar·Home 공유, React Query가 중복 제거) |
| `src/index.css` | 런처 스타일 → 사이드바·홈 스타일로 교체 |

- `src/launcher/` 디렉터리는 `src/shell/`로 대체·삭제
- `types.ts`, `vite.config.ts`, 각 앱 내부는 무변경
- 앱 CSS 스코프(`.app-{id}`)를 위해 콘텐츠 래퍼에 `app-{id}` 클래스 유지
- Laboratory는 `virtual:apps` 레지스트리 밖의 셸 정적 메뉴 — 백엔드 모듈 아님

## 데이터 흐름

- 메뉴 활성화 여부: `/api/modules` 응답의 id 집합에 포함 여부 (VITE_APPS로 번들에서 빠진 앱은 애초에 메뉴에 없음 — 기존 동작 유지)
- 홈 카드 상태줄: `/healthz`의 모듈별 숫자 필드 상위 3개 (기존 statusLine 로직)

## 에러 처리

- 쿼리 실패 시 메뉴는 활성으로 표시(폴백), 홈 카드는 "상태 정보 없음"
- 알 수 없는 경로 세그먼트 → 홈으로 폴백 렌더

## 테스트

- `pnpm tsc --noEmit` 통과
- 브라우저 확인: 홈 렌더, 5개 메뉴 순서, 각 앱 전환, Laboratory 빈 상태, 테마 토글, 좁은 화면 축소

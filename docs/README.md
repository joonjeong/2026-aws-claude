# claude-lab 스펙 모음

네 개의 캡스톤이 **단일 서비스 `hub/`의 모듈**로 통합되어 있다 (2026-08-10).
원 스펙(프롬프트)은 이 디렉토리 루트, 승인된 설계 문서는 `specs/`.

| 모듈 | 원 스펙 | 설계 문서 | 위치 |
|---|---|---|---|
| 통합 서비스 hub | — | specs/2026-08-10-hub-design.md | `hub/` |
| 공용 레이어 labkit | — | specs/2026-08-10-shared-kit-design.md | `shared/` |
| quake (Quake Watch) | earthquake.md | specs/2026-08-10-quake-watch-design.md | `hub/backend/app/modules/quake/` |
| trend (Trend Radar) | youtube.md | specs/2026-08-10-trend-radar-design.md | `hub/backend/app/modules/trend/` |
| news (Newsroom Lens) | newsroom.md | specs/2026-08-10-newsroom-lens-design.md | `hub/backend/app/modules/news/` |
| market (Market Desk) | market.md | specs/2026-08-10-market-desk-design.md | `hub/backend/app/modules/market/` |

개별 모듈 설계 문서의 "구조" 절은 통합 이전 기준 — 구조·배포는 hub 설계 문서(§1·§7)가
우선한다. 프론트엔드 요구사항은 각 원 스펙의 화면 절이 원본 계약이며 hub 설계 문서
§6에 체크리스트로 이관되어 있다.

## 실행

mise 통합 태스크 사용 — 상세는 [루트 README](../README.md).

```bash
mise run setup && mise run start   # uv(백엔드) + pnpm(프론트), :8000 통합 서빙
# ⚠ 이 머신은 omlx-server가 :8000 점유 — PORT=8010 mise run start
```

- 프론트엔드는 **단일 Vite+React 앱** (`hub/frontend/`, 설계:
  specs/2026-08-10-hub-frontend-design.md). 진입점 `/` = 런처, 각 앱은
  `/quake` `/news` `/trend` `/market` 클라이언트 라우트 (딥링크 새로고침 지원).
- **빌드 타임 앱 선택**: `VITE_APPS=quake,market npm run build` — 미선택 앱은
  번들에서 완전 제외. 런처는 "빌드 포함 앱 ∩ 백엔드 활성 모듈"만 활성 카드로.
- API는 `/api/{모듈}/...` 첫 네임스페이스로 구분, `/healthz`는 모듈 집계
- 컨테이너: `docker build -f hub/Dockerfile [--build-arg APPS=...] -t claude-lab-hub .`
- IaC: `hub/infra/` CDK (HubStack), `cdk synth` 검증 완료

## 공통 결정 (2026-08-10)

- 수집/스토어/LLM 공통 패턴은 `shared/labkit` 패키지 — 이후의 **통합 마켓 영향도
  모니터링 솔루션**이 각 모듈 수집기를 import 해 조합하는 것이 전제.
- 배포는 `cdk synth` 클린 통과까지. 실배포는 이후 한 줄.
- API 키(YT_API_KEY, AWS_BEARER_TOKEN_BEDROCK) 부재 시 503/비활성 패널로
  우아하게 저하하는 동작까지가 검증 계약.

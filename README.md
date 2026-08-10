# claude-lab hub

네 개의 캡스톤(지진·뉴스·유튜브 급상승·시황)을 **하나의 서비스**로 통합한 실험실.
백엔드는 `/api/{모듈}` 네임스페이스로, 프론트엔드는 단일 React 앱의 런처에서
모듈을 선택한다. 수집/스토어/LLM 공통 패턴은 `shared/labkit` 패키지로 추상화되어
이후의 통합 마켓 영향도 모니터링 솔루션이 재사용하는 것을 전제로 한다.

| 모듈 | 설명 | 데이터 소스 (키) |
|---|---|---|
| 🌋 quake — Quake Watch | 전 세계 실시간 지진 지도·통계·AI 브리핑 | USGS GeoJSON (불요) |
| 📰 news — Newsroom Lens | 4개 매체 관점 비교(렌즈) 뉴스룸 | BBC·Guardian·NHK·연합 RSS (불요) |
| 📈 trend — Trend Radar | 유튜브 급상승 30 + delta/NEW + 브리핑 | YouTube Data API (`YT_API_KEY`) |
| 📊 market — Market Desk | US·KR 시세, 캔들 차트, AI 분석(SSE) | yfinance·pykrx (불요) |

LLM 기능(브리핑/렌즈/AI 분석)은 Bedrock Converse를 사용하며
`AWS_BEARER_TOKEN_BEDROCK` 환경변수가 없으면 503으로 우아하게 비활성화된다.

## 빠른 시작 (mise 통합 실행)

도구 체인은 [mise](https://mise.jdx.dev)가 관리한다 (node 24, pnpm, uv — `mise.toml`).

```bash
mise trust && mise install   # 최초 1회: 도구 설치
mise run setup               # 의존성: backend(uv sync) + frontend(pnpm install)
mise run start               # 통합 실행: 프론트 빌드 → http://localhost:8000
```

> ⚠ 포트 8000이 사용 중이면(`omlx-server` 등) `PORT=8010 mise run start`.

### 자주 쓰는 태스크

```bash
mise run start               # 프론트 빌드 후 단일 포트 서빙 (운영 모양)
mise run dev                 # 프론트 Vite dev 서버 (:5173, /api는 백엔드로 프록시)
mise run backend:serve       # 백엔드만
mise run build               # 프론트 빌드만 → hub/backend/static/app/
mise run infra:synth         # CDK 스택 synth 검증
```

### 환경변수

| 변수 | 대상 | 설명 |
|---|---|---|
| `PORT` | start/backend:serve | 서빙 포트 (기본 8000) |
| `ENABLED_MODULES` | 백엔드 | 탑재 모듈 선택, 예: `quake,market` (기본 전체) |
| `VITE_APPS` | 프론트 빌드 | **번들에 포함할 앱 선택** — 미선택 앱은 번들에서 완전 제외 |
| `YT_FIXTURE` | trend | 픽스처 스냅샷 경로 — 키 없이 데모: `YT_FIXTURE=../fixtures/trending.json` |
| `YT_API_KEY` | trend | YouTube Data API v3 키 (없으면 빈 목록 + 수집 실패 상태) |
| `AWS_BEARER_TOKEN_BEDROCK` | 전 모듈 | Bedrock LLM 기능 활성화 (없으면 503) |

예 — 두 모듈만, 픽스처 데모, 포트 8010:

```bash
VITE_APPS=quake,trend mise run build
PORT=8010 ENABLED_MODULES=quake,trend YT_FIXTURE=../fixtures/trending.json mise run backend:serve
```

런처(`/`)는 "빌드에 포함된 앱 ∩ 백엔드 활성 모듈"만 활성 카드로 보여준다.

## 구조

```
mise.toml            # 통합 태스크·도구 버전
shared/labkit/       # 공용 레이어: PollingCollector·IdempotentStore·SnapshotRingBuffer·
                     #   TTLCache(single-flight)·Bedrock httpx 클라이언트(버킷 캐시)
hub/
├── backend/         # FastAPI 모듈 조합기 (uv 프로젝트, pyproject.toml + uv.lock)
│   └── app/modules/{quake,news,trend,market}/   # 모듈 계약: META·router·startup·shutdown·health
├── frontend/        # 단일 Vite+React+TS 앱 (pnpm) — src/apps/<id>/ + 런처 + virtual:apps 레지스트리
├── fixtures/        # trend 데모 픽스처
├── infra/           # CDK HubStack (CloudFront → ALB → Fargate, synth까지)
└── Dockerfile       # 멀티스테이지 (pnpm 빌드 → uv 서비스), --build-arg APPS=...
docs/                # 원 스펙 4건 + 설계 문서 6건 (docs/README.md 참조)
```

## API 요약

- `GET /healthz` — 모듈별 상태 집계 · `GET /api/modules` — 런처 카드 데이터
- `GET /api/quake/quakes?hours=24&min_mag=2.5` · `POST /api/quake/brief`
- `GET /api/news/articles` · `POST /api/news/lens`
- `GET /api/trend/trending[?category=id]` · `GET /api/trend/trends?hours=N` · `POST /api/trend/brief?mode=now|daily`
- `GET /api/market/overview·quotes` · `GET /api/market/stocks/{sym}[/chart?range=1w|1m|3m|1y]` · `POST /api/market/ai/stocks/{sym}` (SSE)

오류 계약: LLM 키 없음 → 503, 상류 오류 → 502(상태 코드만 노출), 수집 실패는
모듈 health에 기록되고 앱은 계속 동작한다.

## 컨테이너 / 배포

```bash
docker build -f hub/Dockerfile -t claude-lab-hub .                      # 전체 앱
docker build -f hub/Dockerfile --build-arg APPS=quake,market -t hub .   # 부분 빌드

mise run infra:synth       # CDK 템플릿 검증 (자격증명 불요)
mise run infra:bootstrap   # 계정/리전 최초 1회 (AWS 자격증명 필요)
mise run infra:diff        # 배포 전 변경분 확인
IMAGE_URI=<계정>.dkr.ecr.<리전>.amazonaws.com/claude-lab-hub:latest \
  mise run infra:deploy    # 실배포 — ECR에 push한 이미지 URI 필수
```

배포 후 Secrets Manager의 `BedrockTokenSecretArn` 시크릿에 실제 Bearer 토큰을
수동 등록해야 LLM 기능이 활성화된다 (CDK 코드·이미지에 비밀 없음).

설계 문서와 결정 이력은 [docs/README.md](docs/README.md)에서 시작.

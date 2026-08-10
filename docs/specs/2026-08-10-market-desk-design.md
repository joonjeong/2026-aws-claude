# Market Desk on Web — 웹 시황 대시보드 설계

- 날짜: 2026-08-10
- 상태: 승인됨
- 시간 제약: 2시간 (테스트 생략, curl·브라우저 검증)
- 원 스펙: docs/market.md · 공용 레이어: docs/specs/2026-08-10-shared-kit-design.md (labkit)

## 목적

yfinance(US)·pykrx(KR) 시세를 TTL 캐시 뒤에서 서빙하는 FastAPI + Vite/React/TS
대시보드. 지수/지표 오버뷰, US·KR 종목 테이블, 캔들 차트 상세, Bedrock SSE
스트리밍 AI 분석. 최종은 프론트 빌드를 backend/static에 넣어 :8000 통합 서빙.

## 확정된 결정

| 결정 | 선택 | 근거 |
|---|---|---|
| 공용 레이어 | labkit.TTLCache(single-flight), labkit.config | 시세/차트 캐시가 스펙의 핵심 요구 |
| AI 호출 | boto3 `converse_stream` (labkit.bedrock 미사용) | 스펙 명시 — bearer는 boto3의 AWS_BEARER_TOKEN_BEDROCK 네이티브 지원, 자격 인자 없음, 리전 ap-northeast-2 |
| 종목 목록 | config 상수 US 50 + KR 50 구조, 기본 슬라이스 20+20. **실목록은 사용자가 추후 제공 — 대형주 플레이스홀더로 시작** | 스펙: "실데이터 목록은 설계 직후 이어서 제공" |
| 장 마감 감지 | 거래소별 로컬 시간 창(US 09:30–16:00 ET, KR 09:00–15:30 KST, 주말 제외) 밖이면 TTL 45→600초 | 스펙 4의 단순 충족, 휴장일 캘린더는 YAGNI |
| yfinance 호출 | `yf.download(tickers=..., threads)` 벌크는 asyncio.to_thread로 | yfinance/pykrx는 동기 라이브러리 — 이벤트 루프 블로킹 방지 |
| 키 없음 검증 | AI 엔드포인트 503 + AIPanel 비활성 | 사용자 결정(키 없음), 스펙이 이미 요구하는 동작 |
| 배포 | 없음 (스펙에 IaC 없음) | Phase 4 = 빌드 통합 서빙까지 |

## 1. 구조

```
market/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI, static 마운트(빌드 존재 시)
│   │   ├── core/config.py          # 심볼/지수/지표 상수, TTL, 슬라이스 크기
│   │   ├── services/us.py          # yfinance (bulk download, 지수, 지표)
│   │   ├── services/kr.py          # pykrx 시세 + yfinance ^KS11/^KQ11
│   │   ├── services/charts.py      # OHLC 기간별
│   │   ├── services/ai.py          # boto3 converse_stream → SSE 제너레이터
│   │   └── api/routes.py
│   ├── static/                     # Phase 4에 프론트 빌드 산출물
│   ├── venv + requirements.txt     # fastapi uvicorn yfinance pykrx httpx boto3 ../../shared
├── frontend/                       # Vite + React + TS
│   └── src/ (Dashboard, StockDetail, AIPanel, api/, components/)
```

- 프론트 의존성: @tanstack/react-query, lightweight-charts.

## 2. 데이터 (services/)

- US: `yf.download` 벌크 (심볼 20), 지수 ^GSPC/^IXIC/^DJI, 경제지표(달러인덱스,
  10Y 금리, WTI, 금 등 yfinance 티커). KR: pykrx 시세 20, 지수는 yfinance
  ^KS11/^KQ11. 개별 심볼 실패는 건너뛰고 나머지 응답 (부분 실패 격리).
- 전체 50+50 목록은 config에 두고 `ACTIVE_US/ACTIVE_KR` 슬라이스로 20+20 사용.

## 3. 캐시 — labkit.TTLCache

- 키: `quotes:us`, `quotes:kr`, `overview`, `chart:{symbol}:{range}`,
  `detail:{symbol}`.
- TTL: 시세/오버뷰 45초(장중) / 600초(마감), 차트 1w=300s, 1m=900s, 3m/1y=3600s.
- single-flight로 같은 키 동시 요청은 상류 1회.

## 4. API 계약

| 엔드포인트 | 응답 |
|---|---|
| `GET /api/health` | `{"status":"ok"}` |
| `GET /api/market/overview` | 지수 5 (^GSPC/^IXIC/^DJI/^KS11/^KQ11) + 경제지표 바 데이터 |
| `GET /api/market/quotes` | `{"us":[...],"kr":[...]}` — Symbol/Name/Price/Change/%/Volume |
| `GET /api/stocks/{symbol}` | 가격 헤더 + 기간 수익률 4종(1W/1M/3M/1Y) + 52주 범위·현재 위치 |
| `GET /api/stocks/{symbol}/chart?range=1w\|1m\|3m\|1y` | 캔들 OHLC 배열 (lightweight-charts가 그대로 그릴 형태: time/open/high/low/close) |
| `POST /api/ai/stocks/{symbol}` | text/event-stream — 아래 7 |

## 5. Dashboard 화면

- 상단 경제지표 바 → 지수 카드 5장(등락색) → 종목 테이블(US/KR 탭,
  상승 초록/하락 빨강, 숫자 우측 정렬). react-query `refetchInterval` 45초.

## 6. StockDetail 화면

- 테이블 클릭 진입, 뒤로 가기로 복귀 (react-router 없이 상태 기반 뷰 전환이면 충분).
- StockHeader(현재가·등락률·거래량) / lightweight-charts 캔들(1W/1M/3M/1Y 탭) /
  ReturnsRow(수익률 4종) / Week52Bar(52주 범위 내 현재 위치) / AIPanel.

## 7. AI 분석 (services/ai.py) — SSE 스트리밍

- boto3 `bedrock-runtime.converse_stream`, 모델 global.anthropic.claude-sonnet-4-6,
  maxTokens 1024, 리전 ap-northeast-2. 클라이언트에 자격 인자 없음 —
  `AWS_BEARER_TOKEN_BEDROCK` 환경변수만 (boto3 네이티브 지원). IAM 정책 생성 없음.
- 이벤트 순서: `event: phase`(fetching→analyzing) → `event: delta`(부분 텍스트)* →
  `event: final`. 내용: 기술적 분석/투자 포인트/리스크, 한국어.
- 키 미설정 → 503, 프론트 AIPanel 비활성. 상류 오류는 상태 코드만.
- AIPanel은 fetch 직접 사용 (react-query는 완결 결과 캐시 모델 — 점진 델타 부적합),
  델타 누적 타자기 렌더, 스트리밍 중 phase 배지 표시.

## 8. UI 무드

- 다크 딥네이비 단일 테마, 숫자 우측 정렬 tabular-nums, 상승 초록 ▲ / 하락 빨강 ▼.

## 9. 구현 순서와 검증 (Bedrock 키 없음 전제)

| Phase | 내용 | 검증 |
|---|---|---|
| 1 | 백엔드 코어 4 API + 캐시 | uvicorn + curl (overview/quotes/{symbol}/chart), 연속 호출로 캐시 히트 확인 |
| 2 | Dashboard | Vite dev 서버 브라우저 확인 |
| 3 | StockDetail + 캔들 | 브라우저 확인 |
| 4 | AI SSE + 빌드 통합 | `curl -N -X POST /api/ai/stocks/AAPL` → 503(키 없음), `npm run build` → backend/static, :8000 단일 서빙 확인 |

## 범위 밖 (YAGNI)

- 호가/투자자 동향/뉴스 (스펙이 확장 과제로 명시), 휴장일 캘린더, WebSocket,
  배포 IaC, 자동화 테스트

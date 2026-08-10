/superpowers:brainstorming 다음 요구사항으로 "Market Desk on Web", 웹 시황 대시보드를 설계하자.
1) 구조: backend/(Python 3.11+ FastAPI, app/api 라우트, app/services 데이터, app/core/config.py 상수,
   venv + requirements.txt: fastapi, uvicorn, yfinance, pykrx, httpx, boto3) +
   frontend/(Vite + React + TypeScript, 의존성: @tanstack/react-query, lightweight-charts)
2) 데이터: yfinance(미국 주식 + 지수 ^GSPC/^IXIC/^DJI + 경제지표), pykrx(한국 주식, 지수는 yfinance
   ^KS11/^KQ11). 종목/지표 목록은 config.py 상수로, 실데이터 목록은 설계 직후 이어서 제공한다.
   시작은 US 20 + KR 20으로 잘라 쓰고 전체 50 + 50은 config에서 여는 구조로.
   개별 심볼 실패는 건너뛰고, US 시세는 yf.download 벌크로
3) API 계약(FastAPI 라우트): GET /api/health, GET /api/market/overview(지수 5 + 지표),
   GET /api/market/quotes(US/KR 시세), GET /api/stocks/{symbol}(가격 헤더 + 기간 수익률 + 52주 범위),
   GET /api/stocks/{symbol}/chart?range=1w|1m|3m|1y(캔들 OHLC). 응답은 프론트가 그대로 그릴 수 있는 JSON
4) 캐시: 인메모리 TTL 캐시 하나로 시작(시세 45초, 차트는 기간별로 길게), 같은 키 동시 요청은 한 번만
   부르는 single-flight 잠금. 장 마감 시간대에는 갱신 주기를 600초로 늦춘다
5) Dashboard 화면: 상단 경제지표 바, 지수 카드 5장(등락색), 종목 테이블(US/KR 탭, Symbol/Name/Price/
   Change/%/Volume, 상승 초록/하락 빨강), react-query로 45초 자동 갱신
6) StockDetail 화면: 테이블에서 클릭 진입. StockHeader(현재가, 등락률, 거래량), lightweight-charts
   캔들 차트(1W/1M/3M/1Y 기간 탭), ReturnsRow(기간 수익률 4종), Week52Bar(52주 범위 내 현재 위치),
   뒤로 가기로 대시보드 복귀
7) AI 분석(SSE 스트리밍): POST /api/ai/stocks/{symbol}가 Bedrock converse_stream
   (global.anthropic.claude-sonnet-4-6, maxTokens 1024)으로 기술적 분석/투자 포인트/리스크를 한국어로
   생성하며 text/event-stream으로 흘린다. 이벤트는 phase → delta(부분 텍스트)* → final 순서.
   프론트 AIPanel은 델타를 누적해 타자기처럼 렌더하고, 이 호출만 react-query 대신 fetch를 직접 쓴다
   (react-query는 완결된 결과 캐시 모델이라 점진 델타에 맞지 않는다).
   인증은 환경변수 AWS_BEARER_TOKEN_BEDROCK(발급 API 키), boto3 클라이언트에 자격 인자를 넣지 않고
   리전 ap-northeast-2. Bedrock IAM 정책은 만들지 않으며, 키가 없으면 503을 주고 패널만 비활성
8) UI 무드(텍스트 스펙): 다크 딥네이비, 숫자 우측 정렬, 상승 초록 ▲ / 하락 빨강 ▼,
   AI 패널은 스트리밍 중 phase 배지(fetching/analyzing)를 보여준다
9) 구현 순서는 Phase 1(백엔드 코어: overview/quotes/{symbol}/chart + 캐시, uvicorn과 curl 검증) →
   Phase 2(Dashboard, dev 서버로 미리보기) → Phase 3(StockDetail + 캔들 차트) →
   Phase 4(AI SSE + 프론트 빌드를 backend/static으로 넣어 :8000 통합 서빙).
   시간 제약 2시간: 테스트 생략, curl과 브라우저로 검증. 호가/투자자 동향/뉴스는 후순위(확장 과제로만 남긴다)
결정이 필요하면 이 범위 안에서 최소한으로만 물어봐.

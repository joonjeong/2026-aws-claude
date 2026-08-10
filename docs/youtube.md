/superpowers:brainstorming 다음 요구사항으로 "Trend Radar", 유튜브 급상승 수집/분석 서비스를 설계하자.
1) 구조: backend/(Python 3.11+ FastAPI, app/collector 수집, app/store 스냅샷 저장, app/derive 파생,
   app/api 라우트, app/llm 브리핑, config.py) + frontend/index.html(정적 SPA 한 장, 빌드 없이
   fetch + 렌더). FastAPI가 정적 파일을 함께 서빙해 :8000 하나로 완결
2) 수집기: httpx로 YouTube Data API v3 videos.list(chart=mostPopular, regionCode=KR, maxResults=30,
   part=snippet,statistics)를 주기 호출. 주기는 config로, 워크샵 모드 60초(원작은 3600초).
   videoCategories(hl=ko)는 기동 시 1회, 실패해도 기본 카테고리명으로 동작.
   statistics 값은 문자열 숫자이므로 비정상 값은 0으로(부분 실패 격리, 카드 한 장이 사이클을 못 죽인다).
   상류 에러 본문은 로그에만, 예외와 API 응답에는 상태 코드만(프로젝트 정보 노출 격리)
3) 스냅샷 스토어: 인메모리 링버퍼(최근 48개). 각 스냅샷은 {captured_at, items[30]}이고
   같은 시각 버킷은 한 번만 저장(멱등). 원작은 이 자리를 DynamoDB(pk=scope, sk=시각 버킷,
   attribute_not_exists 멱등 쓰기)로 채운다, 인터페이스를 같게 설계해 교체 가능하게
4) 파생(derive): 최신 스냅샷과 기준선(직전 스냅샷)을 비교해 rank delta(▲n/▼n), NEW(첫 등장),
   이탈 수를 계산. 카테고리별 점유율(30개 중 비율)도 파생
5) API 계약: GET /healthz, GET /api/trending(최신 30 + delta/NEW + 카테고리명),
   GET /api/trending?category={id}(8개 고정 카테고리 필터: Music/Gaming/Entertainment/
   News&Politics/Sports/Film&Animation/Science&Tech/Comedy), GET /api/trends?hours=N
   (시계열: 시각별 카테고리 점유율과 진입/이탈 수), POST /api/brief?mode=now|daily
   (now=현재 스냅샷 요약, daily=기준선과의 비교 브리핑)
6) 브리핑(LLM): Bedrock Converse를 SDK 없이 httpx 직접 REST로 호출한다.
   POST https://bedrock-runtime.ap-northeast-2.amazonaws.com/model/global.anthropic.claude-sonnet-4-6/converse
   Authorization: Bearer(환경변수 AWS_BEARER_TOKEN_BEDROCK), body는 system + messages + inferenceConfig
   (maxTokens 800). 타임아웃/파싱 실패는 상태 코드만 담은 에러로. 결과는 같은 시각 버킷 동안 캐시.
   브리핑 내용: 주제 클러스터 3~4개와 왜 뜨는지, 카테고리 분포에서 읽히는 흐름,
   제작/시청 관점 인사이트 2~3줄, 한국어
7) 화면(텍스트 스펙): 라이트/다크 듀얼 테마(시스템 기본 + 토글 + localStorage, 색은 CSS 변수).
   헤더(타이틀, 마지막 수집 시각, 수동 새로고침, 테마 토글), 통계 바(합산 조회수, 채널 수,
   최다 카테고리, 이탈 수), 카테고리 칩 8개, 30장 카드 그리드(순위 배지 + ▲▼ delta 배지 + NEW 마커,
   16:9 썸네일, 제목 2줄 말줄임, 채널, 조회수/좋아요 축약, 클릭 시 유튜브 새 탭),
   시계열 영역(최근 N시간 카테고리 점유율 누적 막대, 외부 차트 라이브러리 없이 인라인 SVG),
   브리핑 카드(now/daily 모드 버튼)
8) 키의 거처: 두 키(YT_API_KEY, AWS_BEARER_TOKEN_BEDROCK)는 환경변수로만, 코드/응답/로그에 노출 금지.
   화면은 우리 API만 호출한다
9) 구현 순서는 Phase 1(수집기 + 스냅샷 스토어 + trending API, uvicorn과 curl 검증) →
   Phase 2(카드 그리드 + 카테고리 필터 + delta/NEW 배지) → Phase 3(시계열 API + SVG 차트) →
   Phase 4(브리핑 now/daily + 캐시 + 마감). 시간 제약 2시간: 테스트 생략, curl과 브라우저로 검증
결정이 필요하면 이 범위 안에서 최소한으로만 물어봐.

/superpowers:brainstorming 다음 요구사항으로 "Newsroom Lens", 4개 매체의 관점 비교 뉴스룸을 설계하자.
1) 구조: backend/(Python 3.11+ FastAPI, app/collector 수집, app/store, app/api, app/llm, config.py)
   + frontend/index.html(빌드 없는 정적 SPA 한 장). FastAPI가 정적 파일을 함께 서빙해 :8000 완결.
   Dockerfile 한 장
2) 소스 4개(전부 공개 RSS, 키 불요), config.py 상수로:
   BBC World, The Guardian World, NHK World(영문), 연합뉴스 국제 - 각 항목은 {id, 이름, 언어, rss_url}.
   피드 URL은 구현 시점에 각 사 공식 RSS 허브에서 확인해 채운다(하드코딩하되 주석으로 확인일 기록)
3) 수집기: feedparser로 4개 피드를 120초 주기 수집, 소스별 최신 15건을
   {source, title, link, published(UTC ISO), summary(HTML 태그 제거, 300자 절단)}로 정규화.
   피드 하나가 실패해도 나머지는 계속(소스별 실패 격리), 마지막 성공 시각을 소스별로 기록
4) 스토어: link를 멱등 키로 하는 인메모리 딕셔너리(소스별 최대 50건). 같은 기사는 published만 갱신
5) API 계약: GET /healthz, GET /api/articles(소스별 최신 목록 + 소스 상태),
   POST /api/lens (아래 6, 같은 10분 버킷 캐시)
6) 렌즈(LLM, 이 캡스톤의 심장): Bedrock Converse를 SDK 없이 httpx 직접 REST로.
   POST https://bedrock-runtime.ap-northeast-2.amazonaws.com/model/global.anthropic.claude-sonnet-4-6/converse
   Authorization: Bearer(환경변수 AWS_BEARER_TOKEN_BEDROCK), maxTokens 1500.
   입력은 4개 소스의 최신 헤드라인+요약 묶음. 출력은 반드시 JSON만:
   {"clusters":[{"topic":"한국어 토픽명","summary":"공통 사실 2문장",
     "frames":{"bbc":"이 매체의 프레임 1문장","guardian":"...","nhk":"...","yna":"..."},
     "sources":{"bbc":[기사 인덱스],...}}], "overview":"오늘의 미디어 지형 3문장"}
   클러스터는 2개 이상 매체가 다룬 공통 토픽만 3~5개. 다루지 않은 매체의 frame은 "미보도".
   모든 생성 텍스트는 한국어, 기사 제목 원문은 화면에서 병기
7) 화면(텍스트 스펙): 라이트/다크 듀얼 테마. 상단 소스 상태 바(4개 매체, 마지막 수집, 건수).
   기본 뷰는 4열 카드 그리드(매체별 최신 헤드라인, 원문 링크 새 탭, 상대 시각).
   "렌즈" 버튼 → 클러스터 뷰: 토픽 카드마다 공통 요약 + 4개 매체 프레임을 나란히,
   미보도는 회색 처리, 근거 기사 링크 칩. 뷰 전환 토글
8) 키와 윤리: Bearer는 환경변수로만. 기사 본문을 저장하지 않는다(헤드라인+요약+링크만),
   화면 모든 카드에 원문 출처 링크 필수
9) 배포와 순서: CDK로 CloudFront → (prefix list SG + X-Origin-Verify) ALB → Fargate 를 구성,
   Secrets 기동 주입. Phase 1(수집 + 스토어 + /api/articles) → Phase 2(4열 그리드)
   → Phase 3(렌즈 JSON + 클러스터 뷰) → Phase 4(cdk deploy 개장). 2시간 제약: 테스트 생략,
   curl과 브라우저로 검증. 결정이 필요하면 이 범위 안에서 최소한으로만 물어봐.

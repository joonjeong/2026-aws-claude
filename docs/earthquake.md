/superpowers:brainstorming 다음 요구사항으로 "Quake Watch", 전 세계 실시간 지진 모니터를 설계하자.
1) 구조: backend/(Python 3.11+ FastAPI, app/collector 수집, app/store 스냅샷, app/api 라우트,
   app/llm 브리핑, config.py) + frontend/index.html(빌드 없는 정적 SPA 한 장). FastAPI가 정적 파일을
   함께 서빙해 :8000 하나로 완결. 컨테이너는 Dockerfile 한 장
2) 수집기: httpx로 USGS 피드 GET
   https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson 을 60초 주기 폴링.
   각 feature에서 id, properties.mag / place / time(UTC ms), geometry.coordinates[경도, 위도, 깊이km]만
   정규화. 비정상 필드는 0 또는 "unknown"으로 다듬고 계속(부분 실패 격리)
3) 스토어: 이벤트 id를 멱등 키로 하는 인메모리 딕셔너리(최대 500건, 오래된 것부터 제거).
   같은 id는 갱신만 하고 중복 삽입하지 않는다. 신규 진입 id 목록을 사이클마다 기록
4) API 계약: GET /healthz, GET /api/quakes?hours=24&min_mag=2.5 (시간 창과 규모 필터,
   최신순 목록 + 요약 통계: 건수, 최대 규모, 활동 최다 지역), POST /api/brief (아래 6)
5) 화면(텍스트 스펙): 라이트/다크 듀얼 테마(토글 + localStorage). 상단 통계 바(24h 건수, 최대 규모,
   최다 지역, 마지막 수집 시각). 중앙에 등장방형(equirectangular) 세계지도, 외부 라이브러리 없이
   인라인 SVG: 대륙 윤곽은 간이 폴리라인이면 충분, 진앙은 원으로 - 반지름은 규모에 비례(mag*2.2px),
   색은 깊이(얕음 주황 → 깊음 보라), 최근 1시간 이벤트는 펄스 애니메이션. 좌표 변환은
   x=(경도+180)/360*폭, y=(90-위도)/180*높이. 하단에 최근 이벤트 테이블(시각 KST 변환, 규모, 지역, 깊이)과
   규모 필터 슬라이더(2.5~6.0)
6) 브리핑(LLM): Bedrock Converse를 SDK 없이 httpx 직접 REST로.
   POST https://bedrock-runtime.ap-northeast-2.amazonaws.com/model/global.anthropic.claude-sonnet-4-6/converse
   Authorization: Bearer(환경변수 AWS_BEARER_TOKEN_BEDROCK), maxTokens 700.
   입력은 최근 24h 요약 통계와 상위 이벤트 목록, 출력은 한국어 "지난 24시간, 지구는" 브리핑:
   전체 흐름 한 문단, 주목 이벤트 2~3개 해설, 활동 급증 지역. 같은 10분 버킷 동안 결과 캐시
7) 키의 거처: AWS_BEARER_TOKEN_BEDROCK은 환경변수로만. USGS는 키가 없다, 화면은 우리 API만 본다
8) 배포: CDK로 CloudFront → (prefix list SG + X-Origin-Verify) ALB → ECS Fargate 를 구성해 배포한다. Secrets Manager가 Bearer를 기동 시 주입, 이미지에 비밀 없음
9) 구현 순서: Phase 1(수집기 + 스토어 + /api/quakes, curl 검증) → Phase 2(지도 SVG + 테이블 + 필터)
   → Phase 3(브리핑 + 캐시) → Phase 4(cdk deploy와 CloudFront 개장). 시간 제약 2시간:
   테스트 생략, curl과 브라우저로 검증. 결정이 필요하면 이 범위 안에서 최소한으로만 물어봐.

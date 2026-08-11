# 뉴스 렌즈 소스 확장 설계 (5 → 15개)

- 날짜: 2026-08-11
- 상태: 승인됨
- 범위: `hub/backend/app/modules/news/config.py` 단일 파일

## 목적

한국(한겨레·경향·조선·SBS·매경·한경)과 미국(NPR·NYT·Fox·WaPo) 매체 10개를
뉴스 렌즈 SOURCES에 추가한다. 각 피드는 등록 시점에 collector의 실제
User-Agent(`NewsroomLens/0.1`)로 curl 검증하고 확인일을 주석으로 남긴다.

## 확정 결정

- **KBS 등록 보류**: news.kbs.co.kr RSS가 404/에러 리다이렉트, world.kbs.co.kr는
  HTML 허브만 확인됨(2026-08-11). 유효 피드 발견 시 별도 추가.
- **SBS는 TopRssFeed**(주요뉴스) — sectionId=01은 정치 섹션이라 부적합.
- **매경 40300001**(전체뉴스, 경제지 특성상 경제 렌즈 커버) + **한경 /feed/economy**.
  매경은 일반 curl UA에 403을 주는 봇 차단이 있으나 collector UA로는 200 — 주석에 기록.
- **LENS_MAX_TOKENS 4000 → 9000**: 렌즈 프롬프트는 SOURCES에서 동적 생성되어
  15개 매체로 자동 확장되지만, 클러스터당 frames/tones 항목이 3배로 늘어
  기존 예산으로는 절단 재발. 산정: 최대 5클러스터 × 15매체 프레임 + tones ≈
  7000~8000 토큰 + 여유분.
- 그 외 무변경: 폴 부하 15피드/120초 수용 가능, store 소스당 50건 cap 자동 스케일.

## 검증

- pytest 전체 그린 유지 (config 데이터 변경이라 신규 테스트 없음).
- 서버 기동 → 첫 수집 사이클 후 `/healthz`의 news.sources에 15개 전부
  `last_success` 기록 확인. 실패 소스가 있으면 해당 항목 조정 또는 보류.

## 검증된 피드 (2026-08-11, collector UA로 HTTP 200 + RSS 확인)

| id | 매체 | lang | URL |
|---|---|---|---|
| hani | 한겨레 전체 | ko | https://www.hani.co.kr/rss/ |
| khan | 경향신문 전체 | ko | https://www.khan.co.kr/rss/rssdata/total_news.xml |
| chosun | 조선일보 전체 | ko | https://www.chosun.com/arc/outboundfeeds/rss/?outputType=xml |
| sbs | SBS 주요뉴스 | ko | https://news.sbs.co.kr/news/TopRssFeed.do?plink=RSSREADER |
| mk | 매일경제 | ko | https://www.mk.co.kr/rss/40300001/ |
| hankyung | 한국경제 경제 | ko | https://www.hankyung.com/feed/economy |
| npr | NPR Top Stories | en | https://feeds.npr.org/1001/rss.xml |
| nyt | NYT 헤드라인 | en | https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml |
| fox | Fox News Latest | en | https://feeds.foxnews.com/foxnews/latest |
| wapo | Washington Post World | en | https://feeds.washingtonpost.com/rss/world |

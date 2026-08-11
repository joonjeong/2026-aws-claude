"""Newsroom Lens configuration.

Feed URLs were confirmed against each outlet's official RSS hub on
2026-08-10 (curl → HTTP 200, parseable RSS 2.0), per docs/newsroom.md #2.
"""
from labkit.config import env_int, env_str

# Each source: {id, name, lang, rss_url}
SOURCES: list[dict] = [
    {
        "id": "bbc",
        "name": "BBC World",
        "lang": "en",
        # Confirmed 2026-08-10 via BBC's official feed host feeds.bbci.co.uk
        # (linked from bbc.co.uk/news RSS hub). HTTP 200, RSS 2.0.
        "rss_url": "http://feeds.bbci.co.uk/news/world/rss.xml",
    },
    {
        "id": "guardian",
        "name": "The Guardian World",
        "lang": "en",
        # Confirmed 2026-08-10 — the Guardian exposes RSS by appending /rss
        # to any section URL (official Guardian RSS mechanism). HTTP 200, RSS 2.0.
        "rss_url": "https://www.theguardian.com/world/rss",
    },
    {
        "id": "nhk",
        "name": "NHK 국제 (NHK World 대체)",
        "lang": "ja",
        # SUBSTITUTION, confirmed 2026-08-10: NHK World's English news service
        # publishes NO official RSS/Atom feed (https://www3.nhk.or.jp/nhkworld/
        # en/news/feeds/ → 404; the news page links no feed; only a 1-item
        # audio podcast exists, unusable for headlines). The closest official
        # alternative is NHK's own RSS hub (https://www.nhk.or.jp/toppage/rss/
        # index.html), whose 国際/International feed is below. Japanese-language;
        # the lens output is Korean regardless. HTTP 200, RSS 2.0.
        "rss_url": "https://news.web.nhk/n-data/conf/na/rss/cat6.xml",
    },
    {
        "id": "yna",
        "name": "연합뉴스 국제",
        "lang": "ko",
        # Confirmed 2026-08-10 via Yonhap's official RSS hub
        # (https://www.yna.co.kr/rss/index — 국제 feed). HTTP 200, RSS 2.0.
        "rss_url": "https://www.yna.co.kr/rss/international.xml",
    },
    {
        "id": "aljazeera",
        "name": "Al Jazeera",
        "lang": "en",
        # Bonus card A (5th source). Confirmed 2026-08-10 via Al Jazeera's
        # official all-news feed. HTTP 200, RSS 2.0.
        "rss_url": "https://www.aljazeera.com/xml/rss/all.xml",
    },
    # --- 2026-08-11 확장: 한국·미국 10개 매체 (설계: docs/specs/
    # 2026-08-11-news-sources-expansion.md). 전 피드를 collector의 실제
    # User-Agent(NewsroomLens/0.1)로 curl 검증 — HTTP 200 + RSS 2.0.
    # KBS는 유효 RSS 미발견(news.kbs.co.kr 404/에러 리다이렉트)으로 보류.
    {
        "id": "hani",
        "name": "한겨레",
        "lang": "ko",
        # Confirmed 2026-08-11 — 한겨레 전체기사 공식 피드.
        "rss_url": "https://www.hani.co.kr/rss/",
    },
    {
        "id": "khan",
        "name": "경향신문",
        "lang": "ko",
        # Confirmed 2026-08-11 — 경향 공식 RSS 허브의 전체뉴스 피드.
        "rss_url": "https://www.khan.co.kr/rss/rssdata/total_news.xml",
    },
    {
        "id": "chosun",
        "name": "조선일보",
        "lang": "ko",
        # Confirmed 2026-08-11 — Arc 퍼블리싱 공식 아웃바운드 RSS.
        "rss_url": "https://www.chosun.com/arc/outboundfeeds/rss/?outputType=xml",
    },
    {
        "id": "sbs",
        "name": "SBS 뉴스(정치)",
        "lang": "ko",
        # Confirmed 2026-08-11 — TopRssFeed(주요뉴스)는 등록 당일 404로
        # 소멸 확인(일시 200 후 불안정). 섹션 피드만 유효해 프레임 비교
        # 가치가 가장 큰 정치(sectionId=01) 채택.
        "rss_url": "https://news.sbs.co.kr/news/SectionRssFeed.do?sectionId=01",
    },
    {
        "id": "mk",
        "name": "매일경제",
        "lang": "ko",
        # Confirmed 2026-08-11 — 전체뉴스 피드(경제지 특성상 경제 렌즈 커버).
        # 주의: 일반 curl 기본 UA에는 403을 주는 봇 차단이 있으나 collector의
        # NewsroomLens UA로는 200. 수동 재검증 시 UA 지정 필요.
        "rss_url": "https://www.mk.co.kr/rss/40300001/",
    },
    {
        "id": "hankyung",
        "name": "한국경제",
        "lang": "ko",
        # Confirmed 2026-08-11 — 경제 섹션 공식 피드.
        "rss_url": "https://www.hankyung.com/feed/economy",
    },
    {
        "id": "npr",
        "name": "NPR",
        "lang": "en",
        # Confirmed 2026-08-11 — feeds.npr.org Top Stories(1001).
        "rss_url": "https://feeds.npr.org/1001/rss.xml",
    },
    {
        "id": "nyt",
        "name": "NYT",
        "lang": "en",
        # Confirmed 2026-08-11 — 헤드라인+요약 무료 피드. 렌즈는 본문을
        # 저장하지 않으므로 충분.
        "rss_url": "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
    },
    {
        "id": "fox",
        "name": "Fox News",
        "lang": "en",
        # Confirmed 2026-08-11 — 공식 latest 피드.
        "rss_url": "https://feeds.foxnews.com/foxnews/latest",
    },
    {
        "id": "wapo",
        "name": "Washington Post",
        "lang": "en",
        # Confirmed 2026-08-11 — 공식 world 피드. 허브 개편이 잦은 편이라
        # 실패 시 feeds.washingtonpost.com에서 재확인.
        # WaPo는 비브라우저 UA를 403으로 차단(compatible 토큰도 차단 확인)
        # — 피드 리더 관행대로 브라우저 UA 오버라이드로 수집.
        "rss_url": "https://feeds.washingtonpost.com/rss/world",
        "user_agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Safari/537.36"
        ),
    },
]

# Collection
POLL_INTERVAL_S: int = env_int("NEWSROOM_POLL_INTERVAL_S", 120)  # per spec: 120s
FETCH_LATEST_N: int = 15          # newest N normalized per source per cycle
STORE_MAX_PER_SOURCE: int = 50    # IdempotentStore cap per source
SUMMARY_MAX_CHARS: int = 300      # HTML-stripped summary truncation

# Lens (Bedrock Converse via labkit)
# 랩 원문은 1500이었으나 보너스 A·C(5번째 매체 + tones)로 출력 계약이 커져
# 실측 절단 발생(2026-08-10: 1500 토큰 ≈ 1906자 ≈ 클러스터 2.5개 분량).
# 2026-08-11 소스 15개 확장: 클러스터당 frames/tones 항목이 3배로 늘어
# 최대 5클러스터 × 15매체 기준 ~7000-8000 토큰 필요, 여유분 포함 9000.
LENS_MAX_TOKENS: int = env_int("NEWSROOM_LENS_MAX_TOKENS", 9000)
# 생성 실패(절단/계약 위반) 후 재시도 쿨다운. 실패 시 캐시를 비우는 대신
# 이 시간 동안 Bedrock 재호출을 막아, 공개 엔드포인트 스팸으로 버킷 캐시의
# 비용 상한이 무력화되는 것을 방지(버킷당 최대 ~bucket/cooldown회).
LENS_FAIL_COOLDOWN_S: int = env_int("NEWSROOM_LENS_FAIL_COOLDOWN_S", 60)
LENS_BUCKET_S: int = 600          # same 10-minute bucket → cached answer
LENS_MODEL: str = env_str("NEWSROOM_LENS_MODEL", "global.anthropic.claude-sonnet-4-6")
LENS_REGION: str = env_str("NEWSROOM_LENS_REGION", "ap-northeast-2")

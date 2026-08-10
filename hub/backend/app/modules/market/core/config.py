"""Market Desk constants: symbol lists, indices, indicators, cache TTLs.

Symbol lists are the REAL lab lists (Capstone 2 "Market Desk on Web") —
US 50 + KR 50, list order fixed. Only the ACTIVE_* slices (20 + 20) are used.
"""
from __future__ import annotations

from labkit.config import env_int

# ---------------------------------------------------------------------------
# US symbols — real lab list (order fixed; first 20 = active slice)
# ---------------------------------------------------------------------------
US_SYMBOLS: list[tuple[str, str]] = [
    ("AAPL", "Apple"), ("MSFT", "Microsoft"), ("GOOGL", "Alphabet"),
    ("AMZN", "Amazon"), ("NVDA", "NVIDIA"), ("META", "Meta Platforms"),
    ("TSLA", "Tesla"), ("BRK-B", "Berkshire Hathaway"), ("JPM", "JPMorgan Chase"),
    ("V", "Visa"), ("JNJ", "Johnson & Johnson"), ("UNH", "UnitedHealth"),
    ("WMT", "Walmart"), ("MA", "Mastercard"), ("PG", "Procter & Gamble"),
    ("HD", "Home Depot"), ("XOM", "Exxon Mobil"), ("CVX", "Chevron"),
    ("LLY", "Eli Lilly"), ("ABBV", "AbbVie"), ("PFE", "Pfizer"),
    ("KO", "Coca-Cola"), ("PEP", "PepsiCo"), ("MRK", "Merck"),
    ("COST", "Costco"), ("AVGO", "Broadcom"), ("AMD", "AMD"),
    ("ORCL", "Oracle"), ("CRM", "Salesforce"), ("NFLX", "Netflix"),
    ("ADBE", "Adobe"), ("CSCO", "Cisco"), ("ACN", "Accenture"),
    ("TXN", "Texas Instruments"), ("INTC", "Intel"), ("QCOM", "Qualcomm"),
    ("INTU", "Intuit"), ("AMAT", "Applied Materials"), ("BKNG", "Booking Holdings"),
    ("ISRG", "Intuitive Surgical"), ("MDLZ", "Mondelez"), ("ADP", "ADP"),
    ("REGN", "Regeneron"), ("VRTX", "Vertex Pharmaceuticals"), ("GILD", "Gilead Sciences"),
    ("PANW", "Palo Alto Networks"), ("LRCX", "Lam Research"), ("MU", "Micron"),
    ("KLAC", "KLA"), ("SNPS", "Synopsys"),
]

# ---------------------------------------------------------------------------
# KR symbols — real lab list (order fixed; first 20 = active slice)
# ---------------------------------------------------------------------------
KR_SYMBOLS: list[tuple[str, str]] = [
    ("005930", "삼성전자"), ("000660", "SK하이닉스"), ("373220", "LG에너지솔루션"),
    ("005380", "현대차"), ("000270", "기아"), ("207940", "삼성바이오로직스"),
    ("006400", "삼성SDI"), ("035420", "NAVER"), ("035720", "카카오"),
    ("005490", "POSCO홀딩스"), ("068270", "셀트리온"), ("028260", "삼성물산"),
    ("105560", "KB금융"), ("055550", "신한지주"), ("012330", "현대모비스"),
    ("066570", "LG전자"), ("003670", "포스코퓨처엠"), ("051910", "LG화학"),
    ("096770", "SK이노베이션"), ("034730", "SK"), ("000810", "삼성화재"),
    ("003550", "LG"), ("032830", "삼성생명"), ("009150", "삼성전기"),
    ("086790", "하나금융지주"), ("010130", "고려아연"), ("033780", "KT&G"),
    ("011200", "HMM"), ("247540", "에코프로비엠"), ("377300", "카카오페이"),
    ("030200", "KT"), ("017670", "SK텔레콤"), ("018260", "삼성에스디에스"),
    ("036570", "엔씨소프트"), ("316140", "우리금융지주"), ("003490", "HD한국조선해양"),
    ("034020", "두산에너빌리티"), ("011170", "롯데케미칼"), ("024110", "기업은행"),
    ("010950", "S-Oil"), ("006800", "미래에셋증권"), ("004020", "현대제철"),
    ("000720", "현대건설"), ("002790", "아모레G"), ("138040", "메리츠금융지주"),
    ("259960", "크래프톤"), ("326030", "SK바이오팜"), ("323410", "카카오뱅크"),
    ("361610", "SK아이이테크놀로지"), ("352820", "하이브"),
]

# Active slice sizes — full 50+50 stays above; open up via env or edit here.
ACTIVE_US_COUNT = env_int("MARKET_ACTIVE_US", 20)
ACTIVE_KR_COUNT = env_int("MARKET_ACTIVE_KR", 20)
ACTIVE_US: list[tuple[str, str]] = US_SYMBOLS[:ACTIVE_US_COUNT]
ACTIVE_KR: list[tuple[str, str]] = KR_SYMBOLS[:ACTIVE_KR_COUNT]

# ---------------------------------------------------------------------------
# Indices (5) and economic indicators (yfinance tickers)
# ---------------------------------------------------------------------------
INDICES: list[tuple[str, str, str]] = [  # (yf ticker, display name, market)
    ("^GSPC", "S&P 500", "US"),
    ("^IXIC", "NASDAQ", "US"),
    ("^DJI", "Dow Jones", "US"),
    ("^KS11", "KOSPI", "KR"),
    ("^KQ11", "KOSDAQ", "KR"),
]

INDICATORS: list[tuple[str, str]] = [  # (yf ticker, display name) — lab 11종
    ("CL=F", "WTI유"),
    ("GC=F", "금"),
    ("SI=F", "은"),
    ("HG=F", "구리"),
    ("EURUSD=X", "EUR/USD"),
    ("KRW=X", "USD/KRW"),
    ("JPY=X", "USD/JPY"),
    ("CNY=X", "USD/CNY"),
    ("^TNX", "미 10년물"),
    ("BTC-USD", "비트코인"),
    ("ETH-USD", "이더리움"),
]

# ---------------------------------------------------------------------------
# Cache TTLs (seconds) — market-hours aware for quotes/overview/detail
# ---------------------------------------------------------------------------
TTL_OPEN = env_int("MARKET_TTL_OPEN", 45)
TTL_CLOSED = env_int("MARKET_TTL_CLOSED", 600)
CHART_TTL: dict[str, int] = {"1w": 300, "1m": 900, "3m": 3600, "1y": 3600}
ORDERBOOK_TTL = 45   # simulated order book (per symbol)
INVESTORS_TTL = 600  # simulated 10-day investor flows (per symbol)
NEWS_TTL = 300       # Yahoo Finance RSS headlines (per symbol)

# Per-symbol news feed (real): Yahoo Finance RSS. KR codes get a ".KS" suffix.
NEWS_RSS_URL = (
    "https://feeds.finance.yahoo.com/rss/2.0/headline"
    "?s={symbol}&region=US&lang=en-US"
)
NEWS_MAX_ITEMS = 5

# POST /ai/articles input cap (title + text + link, chars) — 413 if over
ARTICLE_MAX_INPUT_CHARS = 6000

# Bedrock (AI panel)
BEDROCK_MODEL_ID = "global.anthropic.claude-sonnet-4-6"
BEDROCK_REGION = "ap-northeast-2"
BEDROCK_MAX_TOKENS = 1024

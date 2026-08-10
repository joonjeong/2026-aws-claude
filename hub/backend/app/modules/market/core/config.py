"""Market Desk constants: symbol lists, indices, indicators, cache TTLs.

Symbol lists are PLACEHOLDERS (liquid large-caps) — the user will supply the
real US 50 + KR 50 lists later. Only the ACTIVE_* slices (20 + 20) are used.
"""
from __future__ import annotations

from labkit.config import env_int

# ---------------------------------------------------------------------------
# US symbols — 50 placeholder liquid large-caps (real list to be supplied later)
# ---------------------------------------------------------------------------
US_SYMBOLS: list[tuple[str, str]] = [
    ("AAPL", "Apple"), ("MSFT", "Microsoft"), ("NVDA", "NVIDIA"),
    ("GOOGL", "Alphabet"), ("AMZN", "Amazon"), ("META", "Meta Platforms"),
    ("TSLA", "Tesla"), ("AVGO", "Broadcom"), ("BRK-B", "Berkshire Hathaway"),
    ("JPM", "JPMorgan Chase"), ("LLY", "Eli Lilly"), ("V", "Visa"),
    ("UNH", "UnitedHealth"), ("XOM", "Exxon Mobil"), ("MA", "Mastercard"),
    ("COST", "Costco"), ("HD", "Home Depot"), ("PG", "Procter & Gamble"),
    ("JNJ", "Johnson & Johnson"), ("WMT", "Walmart"), ("NFLX", "Netflix"),
    ("ABBV", "AbbVie"), ("CRM", "Salesforce"), ("BAC", "Bank of America"),
    ("ORCL", "Oracle"), ("CVX", "Chevron"), ("MRK", "Merck"),
    ("KO", "Coca-Cola"), ("AMD", "AMD"), ("PEP", "PepsiCo"),
    ("TMO", "Thermo Fisher"), ("ADBE", "Adobe"), ("CSCO", "Cisco"),
    ("ACN", "Accenture"), ("LIN", "Linde"), ("MCD", "McDonald's"),
    ("ABT", "Abbott"), ("WFC", "Wells Fargo"), ("IBM", "IBM"),
    ("GE", "GE Aerospace"), ("TXN", "Texas Instruments"), ("QCOM", "Qualcomm"),
    ("INTU", "Intuit"), ("CAT", "Caterpillar"), ("DIS", "Disney"),
    ("VZ", "Verizon"), ("AXP", "American Express"), ("AMGN", "Amgen"),
    ("PM", "Philip Morris"), ("GS", "Goldman Sachs"),
]

# ---------------------------------------------------------------------------
# KR symbols — 50 placeholder liquid large-caps (real list to be supplied later)
# ---------------------------------------------------------------------------
KR_SYMBOLS: list[tuple[str, str]] = [
    ("005930", "삼성전자"), ("000660", "SK하이닉스"), ("373220", "LG에너지솔루션"),
    ("207940", "삼성바이오로직스"), ("005380", "현대차"), ("000270", "기아"),
    ("068270", "셀트리온"), ("005490", "POSCO홀딩스"), ("035420", "NAVER"),
    ("051910", "LG화학"), ("006400", "삼성SDI"), ("003670", "포스코퓨처엠"),
    ("035720", "카카오"), ("012330", "현대모비스"), ("028260", "삼성물산"),
    ("105560", "KB금융"), ("055550", "신한지주"), ("066570", "LG전자"),
    ("032830", "삼성생명"), ("015760", "한국전력"), ("086790", "하나금융지주"),
    ("034730", "SK"), ("011200", "HMM"), ("096770", "SK이노베이션"),
    ("003550", "LG"), ("017670", "SK텔레콤"), ("030200", "KT"),
    ("316140", "우리금융지주"), ("033780", "KT&G"), ("009150", "삼성전기"),
    ("018260", "삼성에스디에스"), ("010130", "고려아연"), ("051900", "LG생활건강"),
    ("090430", "아모레퍼시픽"), ("047050", "포스코인터내셔널"), ("010950", "S-Oil"),
    ("024110", "기업은행"), ("011070", "LG이노텍"), ("000810", "삼성화재"),
    ("161390", "한국타이어앤테크놀로지"), ("352820", "하이브"), ("259960", "크래프톤"),
    ("036570", "엔씨소프트"), ("251270", "넷마블"), ("022100", "포스코DX"),
    ("042700", "한미반도체"), ("000100", "유한양행"), ("128940", "한미약품"),
    ("009830", "한화솔루션"), ("010140", "삼성중공업"),
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

INDICATORS: list[tuple[str, str]] = [  # (yf ticker, display name)
    ("DX-Y.NYB", "달러인덱스"),
    ("^TNX", "미 10년물"),
    ("CL=F", "WTI"),
    ("GC=F", "금"),
    ("KRW=X", "USD/KRW"),
]

# ---------------------------------------------------------------------------
# Cache TTLs (seconds) — market-hours aware for quotes/overview/detail
# ---------------------------------------------------------------------------
TTL_OPEN = env_int("MARKET_TTL_OPEN", 45)
TTL_CLOSED = env_int("MARKET_TTL_CLOSED", 600)
CHART_TTL: dict[str, int] = {"1w": 300, "1m": 900, "3m": 3600, "1y": 3600}

# Bedrock (AI panel)
BEDROCK_MODEL_ID = "global.anthropic.claude-sonnet-4-6"
BEDROCK_REGION = "ap-northeast-2"
BEDROCK_MAX_TOKENS = 1024

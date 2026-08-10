"""Market Desk — hub module (yfinance/pykrx quotes, candle charts, Bedrock AI).

Hub contract: META / router / startup / shutdown / health.
Router paths are RELATIVE; hub mounts them under /api/market — this remaps the
old standalone paths /api/stocks/* and /api/ai/* to /api/market/stocks/* and
/api/market/ai/* (hub design 2026-08-10 §3). /api/market/overview·quotes are
unchanged.

Dev note (CORS): the old standalone main.py added CORSMiddleware for the Vite
dev server (http://localhost:5173). Under the hub the built frontend is served
same-origin at /market/, so CORS is unnecessary and was dropped. For frontend
dev, use the Vite dev-server proxy instead (hub/frontend/market/vite.config.ts
proxies /api -> http://localhost:8000).
"""
from .api.routes import health_info, router, warm_pollers  # noqa: F401  (router: hub contract)

META = {
    "id": "market",
    "title": "Market Desk",
    "tagline": "US·KR 시세 대시보드 — 캔들 차트와 AI 분석",
    "icon": "📈",
}


async def startup() -> None:
    """워밍 폴러 시작 — 대시보드 캐시(overview/quotes)를 미리 데운다.
    상세·차트는 여전히 on-demand (routes.py 폴러 주석 참조)."""
    for p in warm_pollers:
        p.start()


async def shutdown() -> None:
    for p in warm_pollers:
        p.stop()


def health() -> dict:
    return health_info()

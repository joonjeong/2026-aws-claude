"""Hub — 4개 캡스톤을 모듈로 조합하는 단일 서비스.

모듈 계약은 app/modules/__init__.py 참조. main.py는 그 계약만 안다.
"""
import logging
from contextlib import asynccontextmanager
from importlib import import_module
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from . import config
from .archive import archive_counts, prune_poller

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent.parent   # hub/backend
STATIC_DIR = BACKEND_DIR / "static"                     # SPA 빌드 산출물

_modules: dict[str, object] = {}
for mid in config.ENABLED_MODULES:
    try:
        _modules[mid] = import_module(f"app.modules.{mid}")
    except Exception:
        logger.exception("module %r failed to load — skipped", mid)


@asynccontextmanager
async def lifespan(app: FastAPI):
    prune_poller.start()  # 아카이브 프루닝: 기동 직후 1회 + 24시간 간격
    for mid, mod in _modules.items():
        await mod.startup()
        logger.info("module %s started", mid)
    yield
    for mid, mod in reversed(list(_modules.items())):
        await mod.shutdown()
        logger.info("module %s stopped", mid)
    prune_poller.stop()


app = FastAPI(title="claude-lab hub", lifespan=lifespan)

for mid, mod in _modules.items():
    app.include_router(mod.router, prefix=f"/api/{mid}", tags=[mid])


@app.get("/healthz")
async def healthz():
    return {
        "status": "ok",
        "archive": archive_counts(),
        "modules": {mid: mod.health() for mid, mod in _modules.items()},
    }


@app.get("/api/modules")
async def modules():
    return {"modules": [dict(mod.META, path=f"/{mid}/") for mid, mod in _modules.items()]}


# 단일 SPA (hub/frontend 빌드 산출물): 실존 파일은 그대로, 나머지 GET은
# index.html 폴백 (딥링크 /quake 등 새로고침 지원). /api·/healthz는 위 라우트가 선점.
SPA_DIR = STATIC_DIR / "app"
if SPA_DIR.is_dir():

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if full_path.startswith(("api/", "healthz")):
            raise HTTPException(status_code=404)
        candidate = (SPA_DIR / full_path).resolve()
        if (
            full_path
            and candidate.is_relative_to(SPA_DIR)
            and candidate.is_file()
        ):
            return FileResponse(candidate)
        return FileResponse(SPA_DIR / "index.html")

else:
    logger.warning(
        "SPA build not found at %s — run `npm run build` in hub/frontend", SPA_DIR
    )

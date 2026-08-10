"""API contract (relative paths — hub mounts under /api/news):
GET /healthz, GET /articles, POST /lens."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from labkit import BedrockError

from .. import config, service
from ..llm.lens import LensParseError

router = APIRouter()


def _iso(epoch: float | None) -> str | None:
    if epoch is None:
        return None
    return (
        datetime.fromtimestamp(epoch, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


@router.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok", "articles": service.store.total()}


@router.get("/articles")
async def articles() -> dict:
    sources = []
    for source in config.SOURCES:
        status = service.collectors[source["id"]].status
        sources.append(
            {
                "id": source["id"],
                "name": source["name"],
                "lang": source["lang"],
                "last_fetch": _iso(status["last_success"]),
                "last_error": status["last_error"],
                "count": service.store.count(source["id"]),
                "articles": service.store.latest(source["id"]),
            }
        )
    return {"sources": sources}


@router.post("/lens")
async def lens():
    try:
        return await service.lens.generate()
    except BedrockError as exc:
        # 503: AWS_BEARER_TOKEN_BEDROCK unset — friendly, actionable message.
        # 502: upstream failure. Status codes only; upstream bodies stay in logs.
        if exc.status_code == 503:
            message = (
                "렌즈 기능이 아직 잠겨 있어요. 서버에 AWS_BEARER_TOKEN_BEDROCK "
                "환경변수를 설정하면 바로 사용할 수 있습니다."
            )
        else:
            message = "렌즈 생성에 실패했습니다 (상류 오류). 잠시 후 다시 시도해 주세요."
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": "lens_unavailable", "message": message},
        )
    except LensParseError:
        return JSONResponse(
            status_code=502,
            content={
                "error": "lens_bad_output",
                "message": "렌즈 응답을 해석하지 못했습니다. 잠시 후 다시 시도해 주세요.",
            },
        )

"""Liveness is independent of infrastructure; readiness probes real dependencies."""

from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from foodbridge import __version__
from foodbridge.db.health import check_dependencies

router = APIRouter(prefix="/api/v1/health", tags=["health"])


class LiveStatus(BaseModel):
    status: Literal["ok"] = "ok"
    version: str = __version__


class ReadyStatus(BaseModel):
    status: Literal["ready", "not_ready"]
    dependencies: dict[str, Literal["ok", "unavailable"]]


@router.get("/live", response_model=LiveStatus)
def live() -> LiveStatus:
    return LiveStatus()


@router.get("/ready", response_model=ReadyStatus, responses={503: {"model": ReadyStatus}})
async def ready(request: Request) -> JSONResponse:
    dependencies = await check_dependencies(request.app.state.settings)
    is_ready = all(value == "ok" for value in dependencies.values())
    body = ReadyStatus(status="ready" if is_ready else "not_ready", dependencies=dependencies)
    return JSONResponse(body.model_dump(), status_code=200 if is_ready else 503)

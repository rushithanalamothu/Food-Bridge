"""Health and donor intake gateway; see docs/architecture/api.md for implemented routes."""

from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from foodbridge import __version__
from foodbridge.agents.intake.service import utcnow
from foodbridge.api.routes.health import router
from foodbridge.api.routes.intake import router as intake_router
from foodbridge.domain.contracts import ApiError
from foodbridge.domain.errors import AppError
from foodbridge.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="FoodBridge API", version=__version__)
    app.state.settings = settings
    app.state.clock = utcnow

    @app.middleware("http")
    async def request_identity(request: Request, call_next):
        request.state.request_id = uuid4()
        response = await call_next(request)
        response.headers["X-Request-ID"] = str(request.state.request_id)
        return response

    def error_response(request, code, message, status):
        body = ApiError(code=code, message=message, request_id=request.state.request_id)
        return JSONResponse(body.model_dump(mode="json"), status_code=status)

    @app.exception_handler(AppError)
    async def app_error(request: Request, error: AppError):
        return error_response(request, error.code, error.message, error.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        body = ApiError(
            code="validation_error",
            message="Please check the request fields.",
            request_id=request.state.request_id,
            details={".".join(str(p) for p in item["loc"]): item["msg"] for item in error.errors()},
        )
        return JSONResponse(body.model_dump(mode="json"), status_code=422)

    @app.exception_handler(OperationalError)
    async def database_unavailable(request: Request, error: OperationalError):
        return error_response(
            request, "database_unavailable", "Database unavailable. Retry shortly.", 503
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Authorization", "Idempotency-Key"],
    )
    app.include_router(router)
    app.include_router(intake_router)
    return app


app = create_app()

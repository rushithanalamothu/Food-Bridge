"""Only the health API is live in the foundation; see docs/architecture/api.md."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from foodbridge import __version__
from foodbridge.api.routes.health import router
from foodbridge.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="FoodBridge API", version=__version__)
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["Content-Type"],
    )
    app.include_router(router)
    return app


app = create_app()

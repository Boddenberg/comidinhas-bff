from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.error_handlers import register_error_handlers
from app.api.middleware import RequestLoggingMiddleware
from app.api.routes.health import router as health_router
from app.api.routes.root import router as root_router
from app.api.v1.router import router as v1_router
from app.core.config import get_settings
from app.core.lifespan import lifespan
from app.core.logging import setup_logging


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings)
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        summary="Base inicial para um Backend for Frontend.",
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_origin_regex=settings.cors_allowed_origin_regex or None,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
        max_age=86400,
    )
    application.add_middleware(RequestLoggingMiddleware, settings=settings)

    application.include_router(root_router)
    application.include_router(health_router)
    application.include_router(v1_router, prefix="/api/v1")
    register_error_handlers(application)
    return application


app = create_app()

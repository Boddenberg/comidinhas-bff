from fastapi import FastAPI

from app.api.error_handlers import register_error_handlers
from app.api.routes.health import router as health_router
from app.api.routes.root import router as root_router
from app.api.v1.router import router as v1_router
from app.core.config import get_settings
from app.core.lifespan import lifespan


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        summary="Base inicial para um Backend for Frontend.",
        lifespan=lifespan,
    )
    application.include_router(root_router)
    application.include_router(health_router)
    application.include_router(v1_router, prefix="/api/v1")
    register_error_handlers(application)
    return application


app = create_app()

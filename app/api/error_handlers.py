import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.errors import AppError, ExternalServiceError

logger = logging.getLogger(__name__)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        log_method = logger.warning if exc.status_code < 500 else logger.error
        log_method(
            "api.error handled path=%s method=%s status=%s code=%s detail=%s",
            request.url.path,
            request.method,
            exc.status_code,
            exc.code,
            exc.message,
        )
        payload: dict[str, str] = {
            "detail": exc.message,
            "code": exc.code,
        }

        if isinstance(exc, ExternalServiceError):
            payload["service"] = exc.service_name

        return JSONResponse(status_code=exc.status_code, content=payload)

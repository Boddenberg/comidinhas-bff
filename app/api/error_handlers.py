from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.errors import AppError, ExternalServiceError


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        payload: dict[str, str] = {
            "detail": exc.message,
            "code": exc.code,
        }

        if isinstance(exc, ExternalServiceError):
            payload["service"] = exc.service_name

        return JSONResponse(status_code=exc.status_code, content=payload)

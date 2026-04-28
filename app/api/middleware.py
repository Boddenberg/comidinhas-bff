from __future__ import annotations

import logging
import time
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import Settings
from app.core.logging import (
    reset_request_id,
    sanitize_params,
    set_request_id,
    truncate_text,
)

logger = logging.getLogger("app.api.requests")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, settings: Settings) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._settings = settings

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("x-request-id") or uuid4().hex
        token = set_request_id(request_id)
        start = time.perf_counter()

        request_body_preview = None
        if self._settings.log_request_body:
            body = await request.body()
            if body:
                request_body_preview = truncate_text(
                    body.decode("utf-8", errors="replace"),
                    max_chars=self._settings.log_body_max_chars,
                )

        logger.info(
            "api.request.start method=%s path=%s query=%s client=%s body=%s",
            request.method,
            request.url.path,
            sanitize_params(dict(request.query_params)),
            request.client.host if request.client else None,
            request_body_preview,
        )

        try:
            response: Response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.exception(
                "api.request.error method=%s path=%s duration_ms=%.2f",
                request.method,
                request.url.path,
                duration_ms,
            )
            reset_request_id(token)
            raise

        duration_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "api.request.end method=%s path=%s status=%s duration_ms=%.2f",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        reset_request_id(token)
        return response

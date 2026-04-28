from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any

from app.core.config import Settings

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

_SENSITIVE_KEYS = {
    "apikey",
    "api_key",
    "authorization",
    "access_token",
    "refresh_token",
    "password",
    "token",
    "key",
    "supabase_key",
    "openai_api_key",
    "google_maps_api_key",
    "infobip_api_key",
}


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        return True


def setup_logging(settings: Settings) -> None:
    level_name = settings.log_level.upper()
    level = getattr(logging, level_name, logging.INFO)

    logging.basicConfig(
        level=level,
        format=(
            "%(asctime)s %(levelname)s "
            "[%(name)s] [request_id=%(request_id)s] %(message)s"
        ),
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )

    root_logger = logging.getLogger()
    request_id_filter = RequestIdFilter()
    for handler in root_logger.handlers:
        handler.addFilter(request_id_filter)

    logging.getLogger("httpx").setLevel(settings.log_httpx_level.upper())
    logging.getLogger("uvicorn.access").setLevel(settings.log_uvicorn_access_level.upper())


def set_request_id(request_id: str):
    return request_id_ctx.set(request_id)


def reset_request_id(token) -> None:  # type: ignore[no-untyped-def]
    request_id_ctx.reset(token)


def sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return sanitize_mapping(value)
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_value(item) for item in value)
    return value


def sanitize_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in mapping.items():
        if _is_sensitive_key(key):
            sanitized[key] = "***"
        else:
            sanitized[key] = sanitize_value(value)
    return sanitized


def sanitize_params(params: Any) -> Any:
    if params is None:
        return None

    if isinstance(params, dict):
        return sanitize_mapping(params)

    if isinstance(params, (list, tuple)):
        sanitized_items = []
        for item in params:
            if (
                isinstance(item, (list, tuple))
                and len(item) == 2
                and isinstance(item[0], str)
            ):
                key, value = item
                sanitized_items.append((key, "***" if _is_sensitive_key(key) else value))
            else:
                sanitized_items.append(sanitize_value(item))
        return sanitized_items

    return sanitize_value(params)


def truncate_text(value: str | None, *, max_chars: int) -> str | None:
    if value is None or len(value) <= max_chars:
        return value
    return f"{value[:max_chars].rstrip()}..."


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return normalized in _SENSITIVE_KEYS or normalized.endswith("_token")

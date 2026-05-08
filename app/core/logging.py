from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from collections.abc import Mapping, Sequence
from typing import Any

from app.core.config import Settings

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

_SENSITIVE_KEYS = {
    "apikey",
    "api_key",
    "authorization",
    "cookie",
    "set_cookie",
    "access_token",
    "refresh_token",
    "password",
    "secret",
    "client_secret",
    "token",
    "key",
    "supabase_key",
    "supabase_service_role_key",
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


def payload_preview(value: Any, *, max_chars: int) -> str | None:
    if value is None:
        return None

    try:
        loggable = _to_loggable(value)
        sanitized = sanitize_value(loggable)
        text = json.dumps(
            sanitized,
            ensure_ascii=False,
            sort_keys=True,
            default=_json_default,
        )
    except Exception:
        text = str(value)

    return truncate_text(text, max_chars=max_chars)


def response_preview(response: Any, *, max_chars: int) -> str | None:
    content = getattr(response, "content", None)
    if not content:
        return None

    headers = getattr(response, "headers", {}) or {}
    content_type = ""
    try:
        content_type = str(headers.get("content-type", "")).lower()
    except Exception:
        content_type = ""

    if "json" in content_type:
        try:
            return payload_preview(response.json(), max_chars=max_chars)
        except Exception:
            pass

    if isinstance(content, bytes):
        raw = content[: max(max_chars * 4, max_chars)]
        encoding = getattr(response, "encoding", None) or "utf-8"
        try:
            text = raw.decode(encoding, errors="replace")
        except LookupError:
            text = raw.decode("utf-8", errors="replace")
    else:
        text = str(content)

    return truncate_text(text, max_chars=max_chars)


def files_preview(files: Any) -> Any:
    if not files:
        return None

    if isinstance(files, Mapping):
        return {str(key): _file_entry_preview(value) for key, value in files.items()}

    if isinstance(files, Sequence) and not isinstance(files, (str, bytes, bytearray)):
        result = []
        for item in files:
            if (
                isinstance(item, Sequence)
                and not isinstance(item, (str, bytes, bytearray))
                and len(item) == 2
            ):
                result.append((item[0], _file_entry_preview(item[1])))
            else:
                result.append(_file_entry_preview(item))
        return result

    return _file_entry_preview(files)


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return normalized in _SENSITIVE_KEYS or normalized.endswith("_token")


def _to_loggable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(mode="json")
        except TypeError:
            return value.model_dump()

    if isinstance(value, Mapping):
        return {str(key): _to_loggable(item) for key, item in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [_to_loggable(item) for item in value]

    if isinstance(value, bytes):
        return f"<bytes length={len(value)}>"

    if isinstance(value, bytearray):
        return f"<bytearray length={len(value)}>"

    return value


def _file_entry_preview(value: Any) -> Any:
    if isinstance(value, tuple):
        filename = value[0] if len(value) > 0 else None
        content = value[1] if len(value) > 1 else None
        content_type = value[2] if len(value) > 2 else None
        return {
            "filename": filename,
            "content_type": content_type,
            "content_length": len(content) if isinstance(content, (bytes, bytearray)) else None,
        }

    if isinstance(value, (bytes, bytearray)):
        return {"content_length": len(value)}

    return str(value)


def _json_default(value: Any) -> str:
    return str(value)

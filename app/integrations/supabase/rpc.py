from __future__ import annotations

import logging
import time
from typing import Any, Mapping, Sequence
from urllib.parse import quote, urlparse

import httpx

from app.core.config import Settings
from app.core.errors import (
    AuthenticationError,
    BadRequestError,
    ConfigurationError,
    ConflictError,
    ExternalServiceError,
    NotFoundError,
)
from app.core.logging import sanitize_params

logger = logging.getLogger(__name__)

class SupabaseRpcMixin:
    async def call_rpc(
        self,
        *,
        access_token: str | None = None,
        function_name: str,
        payload: dict[str, Any],
    ) -> Any:
        response = await self._request(
            "POST",
            self._build_url("rest", "rpc", function_name),
            headers=self._headers(access_token=access_token),
            json=payload,
            context=f"rpc_{function_name}",
        )
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise ExternalServiceError(
                "supabase",
                f"A funcao RPC {function_name} retornou uma resposta invalida.",
            ) from exc

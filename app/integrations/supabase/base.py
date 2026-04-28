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

class BaseSupabaseClient:
    API_VERSION = "2024-01-01"

    def __init__(self, http_client: httpx.AsyncClient, settings: Settings) -> None:
        self._http_client = http_client
        self._settings = settings

    def get_public_profile_photo_url(self, object_path: str) -> str:
        return self._build_url(
            "storage",
            "object",
            "public",
            self._settings.supabase_profile_bucket,
            object_path,
        )

    def get_public_group_photo_url(self, object_path: str) -> str:
        return self._build_url(
            "storage",
            "object",
            "public",
            self._settings.supabase_group_bucket,
            object_path,
        )

    def get_public_place_photo_url(self, object_path: str) -> str:
        return self._build_url(
            "storage",
            "object",
            "public",
            self._settings.supabase_place_photos_bucket,
            object_path,
        )

    def _build_url(self, service: str, *parts: str) -> str:
        self._ensure_configured()
        base_url = self._settings.supabase_url.rstrip("/") if self._settings.supabase_url else ""
        prefix_map = {
            "auth": "auth/v1",
            "rest": "rest/v1",
            "storage": "storage/v1",
        }
        prefix = prefix_map[service]
        cleaned_parts = [part.strip("/") for part in parts if part]
        path = "/".join([prefix, *cleaned_parts])
        return f"{base_url}/{path}"

    def _headers(
        self,
        *,
        access_token: str | None = None,
        include_content_type: bool = True,
    ) -> dict[str, str]:
        self._ensure_configured()
        key = self._settings.supabase_key
        service_key = self._settings.supabase_service_role_key or key
        if not key:
            raise ConfigurationError(
                "As credenciais do Supabase nao estao configuradas corretamente.",
            )

        service_key = self._settings.supabase_service_role_key or key
        headers = {
            "apikey": key,
            "Authorization": f"Bearer {access_token or service_key}",
            "Accept": "application/json",
            "X-Supabase-Api-Version": self.API_VERSION,
        }
        if include_content_type:
            headers["Content-Type"] = "application/json;charset=UTF-8"
        return headers

    def _redirect_params(self, redirect_to: str | None) -> dict[str, str] | None:
        if redirect_to is None:
            return None
        return {"redirect_to": redirect_to}

    def _normalize_auth_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        user = payload.get("user")
        return {
            "user": user if isinstance(user, dict) else None,
            "session": self._extract_session(payload),
            "email_confirmation_required": self._extract_session(payload) is None,
        }

    @staticmethod
    def _extract_session(payload: dict[str, Any]) -> dict[str, Any] | None:
        access_token = payload.get("access_token")
        refresh_token = payload.get("refresh_token")
        token_type = payload.get("token_type")

        if not isinstance(access_token, str) or not isinstance(refresh_token, str):
            return None

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": token_type if isinstance(token_type, str) else "bearer",
            "expires_in": payload.get("expires_in"),
            "expires_at": payload.get("expires_at"),
        }

    def _ensure_configured(self) -> None:
        if self._settings.is_supabase_configured:
            return

        raise ConfigurationError(
            "Configure SUPABASE_URL e SUPABASE_KEY no arquivo .env ou nas variaveis de ambiente.",
        )

    async def _request_json(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        context: str,
        params: Sequence[tuple[str, str]] | Mapping[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[Any]:
        response = await self._request(
            method,
            url,
            headers=headers,
            params=params,
            json=json,
            context=context,
        )

        if not response.content:
            return {}

        try:
            payload = response.json()
        except ValueError as exc:
            raise ExternalServiceError(
                "supabase",
                "O Supabase retornou uma resposta que nao e JSON.",
            ) from exc

        if isinstance(payload, (dict, list)):
            return payload

        raise ExternalServiceError(
            "supabase",
            "O Supabase retornou um payload em formato inesperado.",
        )

    async def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        context: str,
        params: Sequence[tuple[str, str]] | Mapping[str, str] | None = None,
        json: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> httpx.Response:
        start = time.perf_counter()
        parsed_url = urlparse(url)
        logger.debug(
            "supabase.request.start context=%s method=%s path=%s params=%s has_files=%s",
            context,
            method,
            parsed_url.path,
            sanitize_params(params),
            bool(files),
        )
        try:
            response = await self._http_client.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json,
                files=files,
                data=data,
                timeout=self._settings.supabase_timeout_seconds,
            )
            response.raise_for_status()
            duration_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "supabase.request.end context=%s method=%s path=%s status=%s duration_ms=%.2f",
                context,
                method,
                parsed_url.path,
                response.status_code,
                duration_ms,
            )
            return response
        except httpx.TimeoutException as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.warning(
                "supabase.request.timeout context=%s method=%s path=%s duration_ms=%.2f",
                context,
                method,
                parsed_url.path,
                duration_ms,
            )
            raise ExternalServiceError(
                "supabase",
                "Timeout ao chamar o Supabase.",
            ) from exc
        except httpx.HTTPStatusError as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.warning(
                "supabase.request.http_error context=%s method=%s path=%s status=%s duration_ms=%.2f",
                context,
                method,
                parsed_url.path,
                exc.response.status_code,
                duration_ms,
            )
            self._raise_for_supabase_error(exc.response, context=context)
            raise
        except httpx.HTTPError as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.warning(
                "supabase.request.network_error context=%s method=%s path=%s duration_ms=%.2f",
                context,
                method,
                parsed_url.path,
                duration_ms,
            )
            raise ExternalServiceError(
                "supabase",
                "Erro de rede ao chamar o Supabase.",
            ) from exc

    def _raise_for_supabase_error(self, response: httpx.Response, *, context: str) -> None:
        message = self._extract_error_message(response)
        normalized_message = message.lower()

        if "bucket not found" in normalized_message:
            raise ConfigurationError(
                f"Crie o bucket '{self._settings.supabase_profile_bucket}' no Supabase Storage antes de enviar fotos.",
            )

        if (
            response.status_code == 409
            or "duplicate key" in normalized_message
            or "already registered" in normalized_message
        ):
            raise ConflictError(message)

        if response.status_code in {400, 401, 403} and context.startswith("auth_"):
            raise AuthenticationError(message)

        if response.status_code == 404:
            raise NotFoundError(message)

        if 400 <= response.status_code < 500:
            raise BadRequestError(message)

        raise ExternalServiceError(
            "supabase",
            f"Falha ao chamar o Supabase: {message}",
        )

    @staticmethod
    def _parse_content_range_total(header: str) -> int:
        try:
            if "/" in header:
                total_part = header.split("/")[-1].strip()
                if total_part != "*":
                    return int(total_part)
        except (ValueError, IndexError):
            pass
        return 0

    @staticmethod
    def _extract_error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            payload = None

        if isinstance(payload, dict):
            for key in ("message", "msg", "error_description", "error"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

            hint = payload.get("hint")
            if isinstance(hint, str) and hint.strip():
                return hint.strip()

        return f"HTTP {response.status_code}"

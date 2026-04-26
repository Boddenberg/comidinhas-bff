from __future__ import annotations

from typing import Any
from urllib.parse import quote

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


class SupabaseClient:
    API_VERSION = "2024-01-01"

    def __init__(self, http_client: httpx.AsyncClient, settings: Settings) -> None:
        self._http_client = http_client
        self._settings = settings

    @property
    def max_profile_photo_bytes(self) -> int:
        return self._settings.supabase_profile_photo_max_bytes

    async def sign_up(
        self,
        *,
        email: str,
        password: str,
        metadata: dict[str, Any] | None = None,
        email_redirect_to: str | None = None,
    ) -> dict[str, Any]:
        payload = await self._request_json(
            "POST",
            self._build_url("auth", "signup"),
            headers=self._headers(),
            params=self._redirect_params(email_redirect_to),
            json={
                "email": email,
                "password": password,
                "data": metadata or {},
            },
            context="auth_sign_up",
        )
        return self._normalize_auth_payload(payload)

    async def sign_in(
        self,
        *,
        email: str,
        password: str,
    ) -> dict[str, Any]:
        payload = await self._request_json(
            "POST",
            self._build_url("auth", "token"),
            headers=self._headers(),
            params={"grant_type": "password"},
            json={
                "email": email,
                "password": password,
                "data": {},
            },
            context="auth_sign_in",
        )
        return self._normalize_auth_payload(payload)

    async def refresh_session(self, *, refresh_token: str) -> dict[str, Any]:
        payload = await self._request_json(
            "POST",
            self._build_url("auth", "token"),
            headers=self._headers(),
            params={"grant_type": "refresh_token"},
            json={"refresh_token": refresh_token},
            context="auth_refresh_session",
        )
        return self._normalize_auth_payload(payload)

    async def sign_out(self, *, access_token: str, scope: str = "global") -> None:
        await self._request(
            "POST",
            self._build_url("auth", "logout"),
            headers=self._headers(access_token=access_token),
            params={"scope": scope},
            context="auth_sign_out",
        )

    async def reauthenticate(self, *, access_token: str) -> None:
        await self._request(
            "GET",
            self._build_url("auth", "reauthenticate"),
            headers=self._headers(access_token=access_token),
            context="auth_reauthenticate",
        )

    async def get_user(self, *, access_token: str) -> dict[str, Any]:
        payload = await self._request_json(
            "GET",
            self._build_url("auth", "user"),
            headers=self._headers(access_token=access_token),
            context="auth_get_user",
        )
        if not isinstance(payload, dict):
            raise ExternalServiceError(
                "supabase",
                "A resposta do Supabase para o usuario autenticado veio em formato invalido.",
            )
        return payload

    async def update_user(
        self,
        *,
        access_token: str,
        attributes: dict[str, Any],
        email_redirect_to: str | None = None,
    ) -> dict[str, Any]:
        payload = await self._request_json(
            "PUT",
            self._build_url("auth", "user"),
            headers=self._headers(access_token=access_token),
            params=self._redirect_params(email_redirect_to),
            json=attributes,
            context="auth_update_user",
        )
        if not isinstance(payload, dict):
            raise ExternalServiceError(
                "supabase",
                "A resposta do Supabase ao atualizar o usuario veio em formato invalido.",
            )
        return payload

    async def get_profile(
        self,
        *,
        access_token: str,
        user_id: str,
    ) -> dict[str, Any] | None:
        payload = await self._request_json(
            "GET",
            self._build_url("rest", "profiles"),
            headers=self._headers(access_token=access_token),
            params={
                "select": "*",
                "id": f"eq.{user_id}",
            },
            context="profile_get",
        )
        if not isinstance(payload, list):
            raise ExternalServiceError(
                "supabase",
                "A resposta do Supabase ao buscar o perfil veio em formato invalido.",
            )
        first = payload[0] if payload else None
        return first if isinstance(first, dict) else None

    async def upsert_profile(
        self,
        *,
        access_token: str,
        profile_data: dict[str, Any],
    ) -> dict[str, Any]:
        payload = await self._request_json(
            "POST",
            self._build_url("rest", "profiles"),
            headers={
                **self._headers(access_token=access_token),
                "Prefer": "resolution=merge-duplicates,return=representation",
            },
            params={"on_conflict": "id"},
            json=profile_data,
            context="profile_upsert",
        )
        if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
            raise ExternalServiceError(
                "supabase",
                "O Supabase nao retornou o perfil apos o upsert.",
            )
        return payload[0]

    async def delete_profile(
        self,
        *,
        access_token: str,
        user_id: str,
    ) -> dict[str, Any] | None:
        payload = await self._request_json(
            "DELETE",
            self._build_url("rest", "profiles"),
            headers={
                **self._headers(access_token=access_token),
                "Prefer": "return=representation",
            },
            params={"id": f"eq.{user_id}"},
            context="profile_delete",
        )
        if not isinstance(payload, list):
            raise ExternalServiceError(
                "supabase",
                "A resposta do Supabase ao excluir o perfil veio em formato invalido.",
            )
        first = payload[0] if payload else None
        return first if isinstance(first, dict) else None

    async def upload_profile_photo(
        self,
        *,
        access_token: str,
        object_path: str,
        content: bytes,
        filename: str,
        content_type: str,
    ) -> dict[str, str]:
        encoded_path = "/".join(quote(part, safe="") for part in object_path.split("/"))
        await self._request(
            "POST",
            self._build_url(
                "storage",
                "object",
                self._settings.supabase_profile_bucket,
                encoded_path,
            ),
            headers=self._headers(access_token=access_token, include_content_type=False),
            files={"file": (filename, content, content_type)},
            data={"cacheControl": "3600"},
            context="storage_upload_profile_photo",
        )
        return {
            "path": object_path,
            "public_url": self.get_public_profile_photo_url(object_path),
        }

    async def remove_profile_photo(
        self,
        *,
        access_token: str,
        object_path: str,
    ) -> None:
        await self._request(
            "DELETE",
            self._build_url("storage", "object", self._settings.supabase_profile_bucket),
            headers=self._headers(access_token=access_token),
            json={"prefixes": [object_path]},
            context="storage_remove_profile_photo",
        )

    async def delete_my_account(self, *, access_token: str) -> None:
        await self._request(
            "POST",
            self._build_url("rest", "rpc", "delete_my_account"),
            headers=self._headers(access_token=access_token),
            json={},
            context="auth_delete_my_account",
        )

    def get_public_profile_photo_url(self, object_path: str) -> str:
        return self._build_url(
            "storage",
            "object",
            "public",
            self._settings.supabase_profile_bucket,
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
        if not key:
            raise ConfigurationError(
                "As credenciais do Supabase nao estao configuradas corretamente.",
            )

        headers = {
            "apikey": key,
            "Authorization": f"Bearer {access_token or key}",
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
        params: dict[str, str] | None = None,
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
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> httpx.Response:
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
            return response
        except httpx.TimeoutException as exc:
            raise ExternalServiceError(
                "supabase",
                "Timeout ao chamar o Supabase.",
            ) from exc
        except httpx.HTTPStatusError as exc:
            self._raise_for_supabase_error(exc.response, context=context)
            raise
        except httpx.HTTPError as exc:
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

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

class SupabaseAuthMixin:
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
        access_token: str | None = None,
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
        access_token: str | None = None,
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
        access_token: str | None = None,
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
        access_token: str | None = None,
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
        access_token: str | None = None,
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
        access_token: str | None = None,
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

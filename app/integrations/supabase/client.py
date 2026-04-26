from __future__ import annotations

from typing import Any, Mapping, Sequence
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

    # ------------------------------------------------------------------ groups

    async def list_groups(self, *, access_token: str) -> list[Any]:
        payload = await self._request_json(
            "GET",
            self._build_url("rest", "groups"),
            headers=self._headers(access_token=access_token),
            params=[("select", "*"), ("order", "created_at.desc")],
            context="groups_list",
        )
        if not isinstance(payload, list):
            raise ExternalServiceError("supabase", "Resposta invalida ao listar grupos.")
        return payload

    async def list_user_memberships(
        self,
        *,
        access_token: str | None = None,
        user_id: str,
    ) -> list[Any]:
        payload = await self._request_json(
            "GET",
            self._build_url("rest", "group_members"),
            headers=self._headers(access_token=access_token),
            params=[
                ("profile_id", f"eq.{user_id}"),
                ("select", "group_id,role"),
            ],
            context="group_members_my_list",
        )
        if not isinstance(payload, list):
            raise ExternalServiceError("supabase", "Resposta invalida ao listar memberships.")
        return payload

    async def get_group_with_members(
        self,
        *,
        access_token: str | None = None,
        group_id: str,
    ) -> dict[str, Any] | None:
        payload = await self._request_json(
            "GET",
            self._build_url("rest", "groups"),
            headers=self._headers(access_token=access_token),
            params=[
                ("id", f"eq.{group_id}"),
                (
                    "select",
                    "*,members:group_members("
                    "role,invited_by,created_at,profile_id,"
                    "profile:profile_id(id,full_name,username,avatar_url)"
                    ")",
                ),
            ],
            context="groups_get",
        )
        if not isinstance(payload, list):
            raise ExternalServiceError("supabase", "Resposta invalida ao buscar grupo.")
        first = payload[0] if payload else None
        return first if isinstance(first, dict) else None

    async def insert_group(
        self,
        *,
        access_token: str | None = None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        response = await self._request_json(
            "POST",
            self._build_url("rest", "groups"),
            headers={
                **self._headers(access_token=access_token),
                "Prefer": "return=representation",
            },
            json=payload,
            context="groups_insert",
        )
        if not isinstance(response, list) or not response or not isinstance(response[0], dict):
            raise ExternalServiceError("supabase", "O Supabase nao retornou o grupo apos a insercao.")
        return response[0]

    async def update_group(
        self,
        *,
        access_token: str | None = None,
        group_id: str,
        payload: dict[str, Any],
    ) -> None:
        await self._request(
            "PATCH",
            self._build_url("rest", "groups"),
            headers=self._headers(access_token=access_token),
            params=[("id", f"eq.{group_id}")],
            json=payload,
            context="groups_update",
        )

    async def delete_group(
        self,
        *,
        access_token: str | None = None,
        group_id: str,
    ) -> None:
        await self._request(
            "DELETE",
            self._build_url("rest", "groups"),
            headers=self._headers(access_token=access_token),
            params=[("id", f"eq.{group_id}")],
            context="groups_delete",
        )

    # --------------------------------------------------------- group_members

    async def insert_group_member(
        self,
        *,
        access_token: str | None = None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        response = await self._request_json(
            "POST",
            self._build_url("rest", "group_members"),
            headers={
                **self._headers(access_token=access_token),
                "Prefer": "return=representation",
            },
            json=payload,
            context="group_members_insert",
        )
        if not isinstance(response, list) or not response or not isinstance(response[0], dict):
            raise ExternalServiceError("supabase", "O Supabase nao retornou o membro apos a insercao.")
        return response[0]

    async def delete_group_member(
        self,
        *,
        access_token: str | None = None,
        group_id: str,
        profile_id: str,
    ) -> None:
        await self._request(
            "DELETE",
            self._build_url("rest", "group_members"),
            headers=self._headers(access_token=access_token),
            params=[
                ("group_id", f"eq.{group_id}"),
                ("profile_id", f"eq.{profile_id}"),
            ],
            context="group_members_delete",
        )

    # ----------------------------------------------------------------- profiles helpers

    async def find_profile_by_email(
        self,
        *,
        access_token: str | None = None,
        email: str,
    ) -> dict[str, Any] | None:
        payload = await self._request_json(
            "GET",
            self._build_url("rest", "profiles"),
            headers=self._headers(access_token=access_token),
            params=[
                ("email", f"eq.{email.lower()}"),
                ("select", "id,email,full_name,username"),
            ],
            context="profiles_find_by_email",
        )
        if not isinstance(payload, list):
            return None
        first = payload[0] if payload else None
        return first if isinstance(first, dict) else None

    # ------------------------------------------------------------------ places

    async def list_places(
        self,
        *,
        access_token: str | None = None,
        group_id: str,
        select: str,
        filters: list[tuple[str, str]],
        sort_field: str,
        sort_descending: bool,
        page: int,
        page_size: int,
    ) -> tuple[list[Any], int]:
        range_start = (page - 1) * page_size
        range_end = range_start + page_size - 1
        order_suffix = "desc" if sort_descending else "asc"

        params: list[tuple[str, str]] = [
            ("group_id", f"eq.{group_id}"),
            ("select", select),
            ("order", f"{sort_field}.{order_suffix}"),
        ]
        params.extend(filters)

        response = await self._request(
            "GET",
            self._build_url("rest", "places"),
            headers={
                **self._headers(access_token=access_token),
                "Prefer": "count=exact",
                "Range-Unit": "items",
                "Range": f"{range_start}-{range_end}",
            },
            params=params,
            context="places_list",
        )

        total = self._parse_content_range_total(
            response.headers.get("content-range", ""),
        )
        try:
            rows = response.json() if response.content else []
        except ValueError:
            rows = []
        if not isinstance(rows, list):
            raise ExternalServiceError("supabase", "Resposta invalida ao listar lugares.")
        return rows, total

    async def get_place(
        self,
        *,
        access_token: str | None = None,
        place_id: str,
        select: str,
    ) -> dict[str, Any] | None:
        payload = await self._request_json(
            "GET",
            self._build_url("rest", "places"),
            headers=self._headers(access_token=access_token),
            params=[
                ("id", f"eq.{place_id}"),
                ("select", select),
            ],
            context="places_get",
        )
        if not isinstance(payload, list):
            raise ExternalServiceError("supabase", "Resposta invalida ao buscar lugar.")
        first = payload[0] if payload else None
        return first if isinstance(first, dict) else None

    async def insert_place(
        self,
        *,
        access_token: str | None = None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        response = await self._request_json(
            "POST",
            self._build_url("rest", "places"),
            headers={
                **self._headers(access_token=access_token),
                "Prefer": "return=representation",
            },
            json=payload,
            context="places_insert",
        )
        if not isinstance(response, list) or not response or not isinstance(response[0], dict):
            raise ExternalServiceError("supabase", "O Supabase nao retornou o lugar apos a insercao.")
        return response[0]

    async def update_place(
        self,
        *,
        access_token: str | None = None,
        place_id: str,
        payload: dict[str, Any],
    ) -> None:
        await self._request(
            "PATCH",
            self._build_url("rest", "places"),
            headers=self._headers(access_token=access_token),
            params=[("id", f"eq.{place_id}")],
            json=payload,
            context="places_update",
        )

    async def delete_place(
        self,
        *,
        access_token: str | None = None,
        place_id: str,
    ) -> None:
        await self._request(
            "DELETE",
            self._build_url("rest", "places"),
            headers=self._headers(access_token=access_token),
            params=[("id", f"eq.{place_id}")],
            context="places_delete",
        )

    # --------------------------------------------------------------- place_photos

    @property
    def max_place_photo_bytes(self) -> int:
        return self._settings.supabase_place_photo_max_bytes

    @property
    def place_photos_max_per_place(self) -> int:
        return self._settings.supabase_place_photos_max_per_place

    async def list_place_photos(
        self,
        *,
        access_token: str | None = None,
        place_id: str,
    ) -> list[Any]:
        payload = await self._request_json(
            "GET",
            self._build_url("rest", "place_photos"),
            headers=self._headers(access_token=access_token),
            params=[
                ("place_id", f"eq.{place_id}"),
                ("select", "*"),
                ("order", "sort_order.asc,created_at.asc"),
            ],
            context="place_photos_list",
        )
        if not isinstance(payload, list):
            raise ExternalServiceError("supabase", "Resposta invalida ao listar fotos do lugar.")
        return payload

    async def insert_place_photo(
        self,
        *,
        access_token: str | None = None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        response = await self._request_json(
            "POST",
            self._build_url("rest", "place_photos"),
            headers={
                **self._headers(access_token=access_token),
                "Prefer": "return=representation",
            },
            json=payload,
            context="place_photos_insert",
        )
        if not isinstance(response, list) or not response or not isinstance(response[0], dict):
            raise ExternalServiceError("supabase", "O Supabase nao retornou a foto apos a insercao.")
        return response[0]

    async def update_place_photo(
        self,
        *,
        access_token: str | None = None,
        photo_id: str,
        payload: dict[str, Any],
    ) -> None:
        await self._request(
            "PATCH",
            self._build_url("rest", "place_photos"),
            headers=self._headers(access_token=access_token),
            params=[("id", f"eq.{photo_id}")],
            json=payload,
            context="place_photos_update",
        )

    async def clear_place_cover_photos(
        self,
        *,
        access_token: str | None = None,
        place_id: str,
    ) -> None:
        await self._request(
            "PATCH",
            self._build_url("rest", "place_photos"),
            headers=self._headers(access_token=access_token),
            params=[("place_id", f"eq.{place_id}"), ("is_cover", "eq.true")],
            json={"is_cover": False},
            context="place_photos_clear_cover",
        )

    async def delete_place_photo_record(
        self,
        *,
        access_token: str | None = None,
        photo_id: str,
    ) -> dict[str, Any] | None:
        payload = await self._request_json(
            "DELETE",
            self._build_url("rest", "place_photos"),
            headers={
                **self._headers(access_token=access_token),
                "Prefer": "return=representation",
            },
            params=[("id", f"eq.{photo_id}")],
            context="place_photos_delete",
        )
        if not isinstance(payload, list):
            return None
        first = payload[0] if payload else None
        return first if isinstance(first, dict) else None

    async def upload_place_photo(
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
                self._settings.supabase_place_photos_bucket,
                encoded_path,
            ),
            headers=self._headers(access_token=access_token, include_content_type=False),
            files={"file": (filename, content, content_type)},
            data={"cacheControl": "3600"},
            context="storage_upload_place_photo",
        )
        return {
            "path": object_path,
            "public_url": self.get_public_place_photo_url(object_path),
        }

    async def remove_place_photo_from_storage(
        self,
        *,
        access_token: str | None = None,
        object_path: str,
    ) -> None:
        try:
            await self._request(
                "DELETE",
                self._build_url("storage", "object", self._settings.supabase_place_photos_bucket),
                headers=self._headers(access_token=access_token),
                json={"prefixes": [object_path]},
                context="storage_remove_place_photo",
            )
        except ExternalServiceError:
            pass

    async def count_place_photos(
        self,
        *,
        access_token: str | None = None,
        place_id: str,
    ) -> int:
        response = await self._request(
            "GET",
            self._build_url("rest", "place_photos"),
            headers={
                **self._headers(access_token=access_token),
                "Prefer": "count=exact",
            },
            params=[
                ("place_id", f"eq.{place_id}"),
                ("select", "id"),
            ],
            context="place_photos_count",
        )
        return self._parse_content_range_total(response.headers.get("content-range", ""))

    def get_public_place_photo_url(self, object_path: str) -> str:
        return self._build_url(
            "storage",
            "object",
            "public",
            self._settings.supabase_place_photos_bucket,
            object_path,
        )

    # -------------------------------------------------------------------- rpc

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

    # ----------------------------------------------------------------- static helpers

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
        service_key = self._settings.supabase_service_role_key or key
        if not key:
            raise ConfigurationError(
                "As credenciais do Supabase nao estao configuradas corretamente.",
            )

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

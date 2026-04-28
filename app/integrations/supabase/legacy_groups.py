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

class SupabaseLegacyGroupsMixin:
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

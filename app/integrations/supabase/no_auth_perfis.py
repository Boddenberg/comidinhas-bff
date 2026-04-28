from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

from app.core.errors import ExternalServiceError

logger = logging.getLogger(__name__)

class SupabaseNoAuthPerfisMixin:
    async def list_perfis(self) -> list[Any]:
        payload = await self._request_json(
            "GET",
            self._build_url("rest", "perfis"),
            headers=self._headers(),
            params=[("select", "*"), ("order", "criado_em.asc")],
            context="perfis_list",
        )
        if not isinstance(payload, list):
            raise ExternalServiceError("supabase", "Resposta inválida ao listar perfis.")
        return payload

    async def get_perfil(self, *, perfil_id: str) -> dict[str, Any] | None:
        payload = await self._request_json(
            "GET",
            self._build_url("rest", "perfis"),
            headers=self._headers(),
            params=[("id", f"eq.{perfil_id}"), ("select", "*")],
            context="perfis_get",
        )
        if not isinstance(payload, list):
            raise ExternalServiceError("supabase", "Resposta inválida ao buscar perfil.")
        first = payload[0] if payload else None
        return first if isinstance(first, dict) else None

    async def get_perfil_por_email(self, *, email: str) -> dict[str, Any] | None:
        payload = await self._request_json(
            "GET",
            self._build_url("rest", "perfis"),
            headers=self._headers(),
            params=[("email", f"ilike.{email.lower()}"), ("select", "*")],
            context="perfis_get_by_email",
        )
        if not isinstance(payload, list):
            raise ExternalServiceError("supabase", "Resposta inválida ao buscar perfil por email.")
        first = payload[0] if payload else None
        return first if isinstance(first, dict) else None

    async def insert_perfil(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._request_json(
            "POST",
            self._build_url("rest", "perfis"),
            headers={**self._headers(), "Prefer": "return=representation"},
            json=payload,
            context="perfis_insert",
        )
        if not isinstance(response, list) or not response or not isinstance(response[0], dict):
            raise ExternalServiceError("supabase", "Supabase não retornou o perfil após inserção.")
        return response[0]

    async def update_perfil(self, *, perfil_id: str, payload: dict[str, Any]) -> None:
        await self._request(
            "PATCH",
            self._build_url("rest", "perfis"),
            headers=self._headers(),
            params=[("id", f"eq.{perfil_id}")],
            json=payload,
            context="perfis_update",
        )

    async def delete_perfil(self, *, perfil_id: str) -> None:
        await self._request(
            "DELETE",
            self._build_url("rest", "perfis"),
            headers=self._headers(),
            params=[("id", f"eq.{perfil_id}")],
            json=None,
            context="perfis_delete",
        )

    async def upload_perfil_foto(
        self,
        *,
        object_path: str,
        content: bytes,
        filename: str,
        content_type: str,
    ) -> dict[str, str]:
        encoded_path = "/".join(quote(part, safe="") for part in object_path.split("/"))
        await self._request(
            "POST",
            self._build_url("storage", "object", self._settings.supabase_profile_bucket, encoded_path),
            headers=self._headers(include_content_type=False),
            files={"file": (filename, content, content_type)},
            data={"cacheControl": "3600"},
            context="storage_upload_perfil_foto",
        )
        return {
            "path": object_path,
            "public_url": self.get_public_profile_photo_url(object_path),
        }

    async def remove_perfil_foto(self, *, object_path: str) -> None:
        try:
            await self._request(
                "DELETE",
                self._build_url("storage", "object", self._settings.supabase_profile_bucket),
                headers=self._headers(),
                json={"prefixes": [object_path]},
                context="storage_remove_perfil_foto",
            )
        except ExternalServiceError:
            pass

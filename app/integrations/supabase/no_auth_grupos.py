from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

from app.core.errors import ExternalServiceError

logger = logging.getLogger(__name__)

class SupabaseNoAuthGruposMixin:
    @property
    def max_group_photo_bytes(self) -> int:
        return self._settings.supabase_group_photo_max_bytes

    async def list_grupos(self, *, perfil_id: str | None = None) -> list[Any]:
        params: list[tuple[str, str]] = [("select", "*"), ("order", "criado_em.desc")]
        if perfil_id:
            params.append(("membros", f'cs.[{{"perfil_id":"{perfil_id}"}}]'))

        payload = await self._request_json(
            "GET",
            self._build_url("rest", "grupos"),
            headers=self._headers(),
            params=params,
            context="grupos_list",
        )
        if not isinstance(payload, list):
            raise ExternalServiceError("supabase", "Resposta inválida ao listar grupos.")
        return payload

    async def get_grupo(self, *, grupo_id: str) -> dict[str, Any] | None:
        payload = await self._request_json(
            "GET",
            self._build_url("rest", "grupos"),
            headers=self._headers(),
            params=[("id", f"eq.{grupo_id}"), ("select", "*")],
            context="grupos_get",
        )
        if not isinstance(payload, list):
            raise ExternalServiceError("supabase", "Resposta inválida ao buscar grupo.")
        first = payload[0] if payload else None
        return first if isinstance(first, dict) else None

    async def get_grupo_por_codigo(self, *, codigo: str) -> dict[str, Any] | None:
        payload = await self._request_json(
            "GET",
            self._build_url("rest", "grupos"),
            headers=self._headers(),
            params=[("codigo", f"eq.{codigo}"), ("select", "*")],
            context="grupos_get_by_codigo",
        )
        if not isinstance(payload, list):
            raise ExternalServiceError("supabase", "Resposta invalida ao buscar grupo por codigo.")
        first = payload[0] if payload else None
        return first if isinstance(first, dict) else None

    async def insert_grupo(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._request_json(
            "POST",
            self._build_url("rest", "grupos"),
            headers={**self._headers(), "Prefer": "return=representation"},
            json=payload,
            context="grupos_insert",
        )
        if not isinstance(response, list) or not response or not isinstance(response[0], dict):
            raise ExternalServiceError("supabase", "Supabase não retornou o grupo após inserção.")
        return response[0]

    async def update_grupo(self, *, grupo_id: str, payload: dict[str, Any]) -> None:
        await self._request(
            "PATCH",
            self._build_url("rest", "grupos"),
            headers=self._headers(),
            params=[("id", f"eq.{grupo_id}")],
            json=payload,
            context="grupos_update",
        )

    async def delete_grupo(self, *, grupo_id: str) -> None:
        await self._request(
            "DELETE",
            self._build_url("rest", "grupos"),
            headers=self._headers(),
            params=[("id", f"eq.{grupo_id}")],
            json=None,
            context="grupos_delete",
        )

    async def upload_group_foto(
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
            self._build_url("storage", "object", self._settings.supabase_group_bucket, encoded_path),
            headers=self._headers(include_content_type=False),
            files={"file": (filename, content, content_type)},
            data={"cacheControl": "3600"},
            context="storage_upload_group_foto",
        )
        return {
            "path": object_path,
            "public_url": self.get_public_group_photo_url(object_path),
        }

    async def remove_group_foto(self, *, object_path: str) -> None:
        try:
            await self._request(
                "DELETE",
                self._build_url("storage", "object", self._settings.supabase_group_bucket),
                headers=self._headers(),
                json={"prefixes": [object_path]},
                context="storage_remove_group_foto",
            )
        except ExternalServiceError:
            pass

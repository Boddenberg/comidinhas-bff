from __future__ import annotations

from typing import Any

from app.integrations.supabase.client import SupabaseClient


class SupabaseGruposGateway:
    def __init__(self, client: SupabaseClient) -> None:
        self._client = client

    @property
    def max_group_photo_bytes(self) -> int:
        return self._client.max_group_photo_bytes

    async def list_grupos(self, *, perfil_id: str | None = None) -> list[Any]:
        return await self._client.list_grupos(perfil_id=perfil_id)

    async def get_grupo(self, *, grupo_id: str) -> dict[str, Any] | None:
        return await self._client.get_grupo(grupo_id=grupo_id)

    async def get_grupo_por_codigo(self, *, codigo: str) -> dict[str, Any] | None:
        return await self._client.get_grupo_por_codigo(codigo=codigo)

    async def insert_grupo(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._client.insert_grupo(payload=payload)

    async def update_grupo(self, *, grupo_id: str, payload: dict[str, Any]) -> None:
        await self._client.update_grupo(grupo_id=grupo_id, payload=payload)

    async def delete_grupo(self, *, grupo_id: str) -> None:
        await self._client.delete_grupo(grupo_id=grupo_id)

    async def get_perfil(self, *, perfil_id: str) -> dict[str, Any] | None:
        return await self._client.get_perfil(perfil_id=perfil_id)

    async def get_perfil_por_email(self, *, email: str) -> dict[str, Any] | None:
        return await self._client.get_perfil_por_email(email=email)

    async def upload_group_foto(
        self,
        *,
        object_path: str,
        content: bytes,
        filename: str,
        content_type: str,
    ) -> dict[str, str]:
        return await self._client.upload_group_foto(
            object_path=object_path,
            content=content,
            filename=filename,
            content_type=content_type,
        )

    async def remove_group_foto(self, *, object_path: str) -> None:
        await self._client.remove_group_foto(object_path=object_path)

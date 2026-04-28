from __future__ import annotations

from typing import Any, Protocol


class GruposRepository(Protocol):
    async def list_grupos(self, *, perfil_id: str | None = None) -> list[Any]: ...
    async def get_grupo(self, *, grupo_id: str) -> dict[str, Any] | None: ...
    async def get_grupo_por_codigo(self, *, codigo: str) -> dict[str, Any] | None: ...
    async def insert_grupo(self, *, payload: dict[str, Any]) -> dict[str, Any]: ...
    async def update_grupo(self, *, grupo_id: str, payload: dict[str, Any]) -> None: ...
    async def delete_grupo(self, *, grupo_id: str) -> None: ...


class PerfisLookup(Protocol):
    async def get_perfil(self, *, perfil_id: str) -> dict[str, Any] | None: ...
    async def get_perfil_por_email(self, *, email: str) -> dict[str, Any] | None: ...


class GrupoPhotoStorage(Protocol):
    @property
    def max_group_photo_bytes(self) -> int: ...

    async def upload_group_foto(
        self,
        *,
        object_path: str,
        content: bytes,
        filename: str,
        content_type: str,
    ) -> dict[str, str]: ...

    async def remove_group_foto(self, *, object_path: str) -> None: ...


class GruposGateway(GruposRepository, PerfisLookup, GrupoPhotoStorage, Protocol):
    pass

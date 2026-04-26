from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import UploadFile

from app.core.errors import BadRequestError, NotFoundError
from app.integrations.supabase.client import SupabaseClient
from app.modules.perfis.schemas import (
    PerfilCreateRequest,
    PerfilListResponse,
    PerfilResponse,
    PerfilUpdateRequest,
)

_TIPOS_IMAGEM = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}


class ManagePerfisUseCase:
    def __init__(self, client: SupabaseClient) -> None:
        self._client = client

    async def listar(self) -> PerfilListResponse:
        rows = await self._client.list_perfis()
        items = [self._mapear(r) for r in rows if isinstance(r, dict)]
        return PerfilListResponse(items=items, total=len(items))

    async def buscar(self, *, perfil_id: str) -> PerfilResponse:
        raw = await self._client.get_perfil(perfil_id=perfil_id)
        if raw is None:
            raise NotFoundError("Perfil não encontrado.")
        return self._mapear(raw)

    async def buscar_por_email(self, *, email: str) -> PerfilResponse:
        raw = await self._client.get_perfil_por_email(email=email)
        if raw is None:
            raise NotFoundError("Nenhum perfil encontrado com este email.")
        return self._mapear(raw)

    async def criar(self, *, request: PerfilCreateRequest) -> PerfilResponse:
        payload: dict[str, Any] = request.model_dump(exclude_unset=False)
        criado = await self._client.insert_perfil(payload=payload)
        return self._mapear(criado)

    async def atualizar(self, *, perfil_id: str, request: PerfilUpdateRequest) -> PerfilResponse:
        payload = request.model_dump(exclude_unset=True)
        if not payload:
            raise BadRequestError("Informe ao menos um campo para atualizar.")
        await self._client.update_perfil(perfil_id=perfil_id, payload=payload)
        return await self.buscar(perfil_id=perfil_id)

    async def remover(self, *, perfil_id: str) -> dict[str, Any]:
        raw = await self._client.get_perfil(perfil_id=perfil_id)
        if raw is None:
            raise NotFoundError("Perfil não encontrado.")
        if raw.get("foto_caminho"):
            await self._client.remove_perfil_foto(object_path=raw["foto_caminho"])
        await self._client.delete_perfil(perfil_id=perfil_id)
        return {"sucesso": True, "mensagem": "Perfil removido com sucesso."}

    async def upload_foto(self, *, perfil_id: str, file: UploadFile) -> PerfilResponse:
        content_type = file.content_type or ""
        ext = _TIPOS_IMAGEM.get(content_type)
        if ext is None:
            raise BadRequestError("Envie uma imagem JPG, PNG, WEBP ou GIF.")

        conteudo = await file.read()
        if not conteudo:
            raise BadRequestError("Arquivo vazio.")
        if len(conteudo) > self._client.max_profile_photo_bytes:
            raise BadRequestError(
                f"Foto excede o limite de {self._client.max_profile_photo_bytes // (1024 * 1024)}MB."
            )

        raw = await self._client.get_perfil(perfil_id=perfil_id)
        if raw is None:
            raise NotFoundError("Perfil não encontrado.")

        if raw.get("foto_caminho"):
            await self._client.remove_perfil_foto(object_path=raw["foto_caminho"])

        caminho = f"{perfil_id}/{uuid4().hex}.{ext}"
        upload = await self._client.upload_perfil_foto(
            object_path=caminho,
            content=conteudo,
            filename=file.filename or f"foto.{ext}",
            content_type=content_type,
        )
        await self._client.update_perfil(
            perfil_id=perfil_id,
            payload={"foto_url": upload["public_url"], "foto_caminho": caminho},
        )
        return await self.buscar(perfil_id=perfil_id)

    async def remover_foto(self, *, perfil_id: str) -> PerfilResponse:
        raw = await self._client.get_perfil(perfil_id=perfil_id)
        if raw is None:
            raise NotFoundError("Perfil não encontrado.")
        if raw.get("foto_caminho"):
            await self._client.remove_perfil_foto(object_path=raw["foto_caminho"])
        await self._client.update_perfil(
            perfil_id=perfil_id,
            payload={"foto_url": None, "foto_caminho": None},
        )
        return await self.buscar(perfil_id=perfil_id)

    @staticmethod
    def _mapear(raw: dict[str, Any]) -> PerfilResponse:
        return PerfilResponse(
            id=str(raw.get("id", "")),
            nome=str(raw.get("nome", "")),
            email=raw.get("email"),
            bio=raw.get("bio"),
            cidade=raw.get("cidade"),
            foto_url=raw.get("foto_url"),
            criado_em=raw.get("criado_em"),
            atualizado_em=raw.get("atualizado_em"),
        )

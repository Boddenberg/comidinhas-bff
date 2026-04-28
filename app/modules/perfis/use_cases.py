from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from fastapi import UploadFile

from app.core.errors import BadRequestError, NotFoundError
from app.integrations.supabase.client import SupabaseClient
from app.modules.grupos.schemas import PapelMembro, TipoGrupo
from app.modules.perfis.schemas import (
    PerfilCreateRequest,
    PerfilListResponse,
    PerfilResponse,
    PerfilUpdateRequest,
)

logger = logging.getLogger(__name__)

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
        logger.info("perfis.listar.start")
        rows = await self._client.list_perfis()
        items = [self._mapear(r) for r in rows if isinstance(r, dict)]
        logger.info("perfis.listar.end total=%s", len(items))
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
        logger.info("perfis.criar.start nome=%s has_email=%s", request.nome, bool(request.email))
        payload: dict[str, Any] = request.model_dump(exclude_unset=False)
        criado = await self._client.insert_perfil(payload=payload)
        grupo = await self._garantir_grupo_individual(perfil=criado)
        criado["grupo_individual_id"] = grupo["id"]
        response = self._mapear(criado)
        logger.info(
            "perfis.criar.end perfil_id=%s grupo_individual_id=%s",
            response.id,
            response.grupo_individual_id,
        )
        return response

    async def atualizar(self, *, perfil_id: str, request: PerfilUpdateRequest) -> PerfilResponse:
        logger.info("perfis.atualizar.start perfil_id=%s fields=%s", perfil_id, sorted(request.model_fields_set))
        payload = request.model_dump(exclude_unset=True)
        if not payload:
            raise BadRequestError("Informe ao menos um campo para atualizar.")
        await self._client.update_perfil(perfil_id=perfil_id, payload=payload)
        response = await self.buscar(perfil_id=perfil_id)
        logger.info("perfis.atualizar.end perfil_id=%s", perfil_id)
        return response

    async def remover(self, *, perfil_id: str) -> dict[str, Any]:
        logger.info("perfis.remover.start perfil_id=%s", perfil_id)
        raw = await self._client.get_perfil(perfil_id=perfil_id)
        if raw is None:
            raise NotFoundError("Perfil não encontrado.")
        if raw.get("foto_caminho"):
            await self._client.remove_perfil_foto(object_path=raw["foto_caminho"])
        if raw.get("grupo_individual_id"):
            await self._client.delete_grupo(grupo_id=str(raw["grupo_individual_id"]))
        await self._client.delete_perfil(perfil_id=perfil_id)
        logger.info("perfis.remover.end perfil_id=%s", perfil_id)
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

    async def _garantir_grupo_individual(self, *, perfil: dict[str, Any]) -> dict[str, Any]:
        perfil_id = str(perfil.get("id", ""))
        if not perfil_id:
            raise BadRequestError("Nao foi possivel criar o espaco individual do perfil.")

        grupo_individual_id = perfil.get("grupo_individual_id")
        if isinstance(grupo_individual_id, str) and grupo_individual_id:
            grupo = await self._client.get_grupo(grupo_id=grupo_individual_id)
            if grupo is not None:
                return grupo

        membro = {
            "perfil_id": perfil_id,
            "nome": perfil.get("nome"),
            "email": perfil.get("email"),
            "papel": PapelMembro.DONO.value,
        }
        grupo = await self._client.insert_grupo(
            payload={
                "nome": perfil.get("nome") or "Meu perfil",
                "tipo": TipoGrupo.INDIVIDUAL.value,
                "descricao": None,
                "dono_perfil_id": perfil_id,
                "membros": [membro],
            }
        )
        await self._client.update_perfil(
            perfil_id=perfil_id,
            payload={"grupo_individual_id": grupo["id"]},
        )
        return grupo

    @staticmethod
    def _mapear(raw: dict[str, Any]) -> PerfilResponse:
        return PerfilResponse(
            id=str(raw.get("id", "")),
            nome=str(raw.get("nome", "")),
            email=raw.get("email"),
            bio=raw.get("bio"),
            cidade=raw.get("cidade"),
            foto_url=raw.get("foto_url"),
            grupo_individual_id=raw.get("grupo_individual_id"),
            criado_em=raw.get("criado_em"),
            atualizado_em=raw.get("atualizado_em"),
        )

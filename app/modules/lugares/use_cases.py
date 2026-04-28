from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from fastapi import UploadFile

from app.core.errors import BadRequestError, NotFoundError
from app.integrations.supabase.client import SupabaseClient
from app.modules.lugares.schemas import (
    FotoSchema,
    LugarCreateRequest,
    LugarFiltros,
    LugarListResponse,
    LugarResponse,
    LugarUpdateRequest,
    ReordenarFotosRequest,
    StatusLugar,
)

logger = logging.getLogger(__name__)

_TIPOS_IMAGEM = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}


class ManageLugaresUseCase:
    SELECT = "*"

    def __init__(self, client: SupabaseClient) -> None:
        self._client = client

    async def listar(self, *, filtros: LugarFiltros) -> LugarListResponse:
        logger.info(
            "lugares.listar.start grupo_id=%s pagina=%s tamanho=%s status=%s favorito=%s",
            filtros.grupo_id,
            filtros.pagina,
            filtros.tamanho_pagina,
            filtros.status.value if filtros.status else None,
            filtros.favorito,
        )
        rows, total = await self._client.list_lugares(
            grupo_id=filtros.grupo_id,
            select=self.SELECT,
            filters=filtros.para_filtros_supabase(),
            sort_field=filtros.ordenar_por.value,
            sort_descending=filtros.direcao.value == "desc",
            page=filtros.pagina,
            page_size=filtros.tamanho_pagina,
        )
        items = [self._mapear(r) for r in rows if isinstance(r, dict)]
        tem_mais = (filtros.pagina * filtros.tamanho_pagina) < total
        logger.info(
            "lugares.listar.end grupo_id=%s items=%s total=%s tem_mais=%s",
            filtros.grupo_id,
            len(items),
            total,
            tem_mais,
        )
        return LugarListResponse(
            items=items,
            pagina=filtros.pagina,
            tamanho_pagina=filtros.tamanho_pagina,
            total=total,
            tem_mais=tem_mais,
        )

    async def buscar(self, *, lugar_id: str) -> LugarResponse:
        raw = await self._client.get_lugar(lugar_id=lugar_id, select=self.SELECT)
        if raw is None:
            raise NotFoundError("Lugar não encontrado.")
        return self._mapear(raw)

    async def criar(self, *, request: LugarCreateRequest) -> LugarResponse:
        logger.info(
            "lugares.criar.start grupo_id=%s nome=%s status=%s favorito=%s autor_perfil_id=%s",
            request.grupo_id,
            request.nome,
            request.status.value,
            request.favorito,
            request.adicionado_por_perfil_id,
        )
        payload: dict[str, Any] = request.model_dump(exclude_unset=False)
        if isinstance(payload.get("status"), StatusLugar):
            payload["status"] = payload["status"].value
        await self._preparar_autor(payload=payload, grupo_id=request.grupo_id)
        criado = await self._client.insert_lugar(payload=payload)
        response = self._mapear(criado)
        logger.info("lugares.criar.end lugar_id=%s grupo_id=%s", response.id, response.grupo_id)
        return response

    async def atualizar(self, *, lugar_id: str, request: LugarUpdateRequest) -> LugarResponse:
        logger.info("lugares.atualizar.start lugar_id=%s fields=%s", lugar_id, sorted(request.model_fields_set))
        payload = request.model_dump(exclude_unset=True)
        if not payload:
            raise BadRequestError("Informe ao menos um campo para atualizar.")
        if isinstance(payload.get("status"), StatusLugar):
            payload["status"] = payload["status"].value

        if "adicionado_por_perfil_id" in payload and payload["adicionado_por_perfil_id"] is not None:
            lugar_raw = await self._client.get_lugar(lugar_id=lugar_id, select="id,grupo_id")
            if lugar_raw is None:
                raise NotFoundError("Lugar nÃ£o encontrado.")
            await self._preparar_autor(
                payload=payload,
                grupo_id=str(lugar_raw.get("grupo_id", "")),
            )

        await self._client.update_lugar(lugar_id=lugar_id, payload=payload)
        response = await self.buscar(lugar_id=lugar_id)
        logger.info("lugares.atualizar.end lugar_id=%s", lugar_id)
        return response

    async def remover(self, *, lugar_id: str) -> dict[str, Any]:
        logger.info("lugares.remover.start lugar_id=%s", lugar_id)
        lugar = await self._client.get_lugar(lugar_id=lugar_id, select="id,grupo_id,fotos")
        if lugar:
            for foto in lugar.get("fotos") or []:
                if isinstance(foto, dict) and foto.get("caminho"):
                    await self._client.remove_lugar_foto(object_path=foto["caminho"])
            await self._remover_lugar_dos_guias(
                grupo_id=str(lugar.get("grupo_id", "")),
                lugar_id=lugar_id,
            )
        await self._client.delete_lugar(lugar_id=lugar_id)
        logger.info("lugares.remover.end lugar_id=%s", lugar_id)
        return {"sucesso": True, "mensagem": "Lugar removido com sucesso."}

    # ------------------------------------------------------------------ fotos

    async def adicionar_foto(
        self,
        *,
        lugar_id: str,
        file: UploadFile,
        definir_como_capa: bool = False,
    ) -> FotoSchema:
        content_type = file.content_type or ""
        ext = _TIPOS_IMAGEM.get(content_type)
        if ext is None:
            raise BadRequestError("Envie uma imagem JPG, PNG, WEBP ou GIF.")

        conteudo = await file.read()
        if not conteudo:
            raise BadRequestError("Arquivo vazio.")
        if len(conteudo) > self._client.max_lugar_foto_bytes:
            raise BadRequestError(f"Foto excede o limite de {self._client.max_lugar_foto_bytes // (1024*1024)}MB.")

        lugar_raw = await self._client.get_lugar(lugar_id=lugar_id, select="id,grupo_id,fotos,imagem_capa")
        if lugar_raw is None:
            raise NotFoundError("Lugar não encontrado.")

        fotos = self._parse_fotos(lugar_raw.get("fotos"))
        if len(fotos) >= self._client.max_fotos_por_lugar:
            raise BadRequestError(f"Limite de {self._client.max_fotos_por_lugar} fotos atingido.")

        grupo_id = str(lugar_raw.get("grupo_id", ""))
        caminho = f"{grupo_id}/{lugar_id}/{uuid4().hex}.{ext}"
        upload = await self._client.upload_lugar_foto(
            object_path=caminho,
            content=conteudo,
            filename=file.filename or f"foto.{ext}",
            content_type=content_type,
        )

        e_capa = definir_como_capa or len(fotos) == 0
        if e_capa:
            for f in fotos:
                f.capa = False

        nova_foto = FotoSchema(
            id=uuid4().hex,
            url=upload["public_url"],
            caminho=upload["path"],
            ordem=len(fotos),
            capa=e_capa,
        )
        fotos.append(nova_foto)

        await self._client.update_lugar(
            lugar_id=lugar_id,
            payload={
                "fotos": [f.model_dump() for f in fotos],
                "imagem_capa": nova_foto.url if e_capa else lugar_raw.get("imagem_capa"),
            },
        )
        return nova_foto

    async def definir_capa(self, *, lugar_id: str, foto_id: str) -> FotoSchema:
        lugar_raw = await self._client.get_lugar(lugar_id=lugar_id, select="id,fotos")
        if lugar_raw is None:
            raise NotFoundError("Lugar não encontrado.")

        fotos = self._parse_fotos(lugar_raw.get("fotos"))
        alvo = next((f for f in fotos if f.id == foto_id), None)
        if alvo is None:
            raise NotFoundError("Foto não encontrada neste lugar.")

        for f in fotos:
            f.capa = f.id == foto_id

        await self._client.update_lugar(
            lugar_id=lugar_id,
            payload={
                "fotos": [f.model_dump() for f in fotos],
                "imagem_capa": alvo.url,
            },
        )
        alvo.capa = True
        return alvo

    async def remover_foto(self, *, lugar_id: str, foto_id: str) -> dict[str, Any]:
        lugar_raw = await self._client.get_lugar(lugar_id=lugar_id, select="id,fotos,imagem_capa")
        if lugar_raw is None:
            raise NotFoundError("Lugar não encontrado.")

        fotos = self._parse_fotos(lugar_raw.get("fotos"))
        alvo = next((f for f in fotos if f.id == foto_id), None)
        if alvo is None:
            raise NotFoundError("Foto não encontrada neste lugar.")

        era_capa = alvo.capa
        fotos = [f for f in fotos if f.id != foto_id]

        for idx, f in enumerate(fotos):
            f.ordem = idx
        if era_capa and fotos:
            fotos[0].capa = True

        nova_capa_url = fotos[0].url if era_capa and fotos else (None if era_capa else lugar_raw.get("imagem_capa"))

        await self._client.update_lugar(
            lugar_id=lugar_id,
            payload={
                "fotos": [f.model_dump() for f in fotos],
                "imagem_capa": nova_capa_url,
            },
        )
        if alvo.caminho:
            await self._client.remove_lugar_foto(object_path=alvo.caminho)

        return {"sucesso": True, "mensagem": "Foto removida com sucesso."}

    async def reordenar_fotos(self, *, lugar_id: str, request: ReordenarFotosRequest) -> LugarResponse:
        lugar_raw = await self._client.get_lugar(lugar_id=lugar_id, select="id,fotos,imagem_capa")
        if lugar_raw is None:
            raise NotFoundError("Lugar não encontrado.")

        fotos = self._parse_fotos(lugar_raw.get("fotos"))
        fotos_por_id = {f.id: f for f in fotos}

        for foto_id in request.ids_fotos:
            if foto_id not in fotos_por_id:
                raise BadRequestError(f"Foto '{foto_id}' não pertence a este lugar.")

        fotos_reordenadas = [fotos_por_id[fid] for fid in request.ids_fotos]
        for idx, f in enumerate(fotos_reordenadas):
            f.ordem = idx

        capa = next((f for f in fotos_reordenadas if f.capa), None)
        capa_url = capa.url if capa else lugar_raw.get("imagem_capa")

        await self._client.update_lugar(
            lugar_id=lugar_id,
            payload={
                "fotos": [f.model_dump() for f in fotos_reordenadas],
                "imagem_capa": capa_url,
            },
        )
        return await self.buscar(lugar_id=lugar_id)

    @staticmethod
    def _parse_fotos(raw: Any) -> list[FotoSchema]:
        if not isinstance(raw, list):
            return []
        result = []
        for item in raw:
            if isinstance(item, dict):
                try:
                    result.append(FotoSchema(**item))
                except Exception:
                    pass
        return sorted(result, key=lambda f: f.ordem)

    async def _preparar_autor(self, *, payload: dict[str, Any], grupo_id: str) -> None:
        grupo = await self._client.get_grupo(grupo_id=grupo_id)
        if grupo is None:
            raise NotFoundError("Grupo nao encontrado.")

        perfil_id = payload.get("adicionado_por_perfil_id")
        if perfil_id is None:
            return

        perfil = await self._client.get_perfil(perfil_id=str(perfil_id))
        if perfil is None:
            raise NotFoundError("Perfil nao encontrado.")

        if not self._perfil_esta_no_grupo(grupo=grupo, perfil_id=str(perfil_id)):
            raise BadRequestError("O perfil informado nao faz parte deste grupo.")

        if not payload.get("adicionado_por"):
            payload["adicionado_por"] = perfil.get("nome")

    @staticmethod
    def _perfil_esta_no_grupo(*, grupo: dict[str, Any], perfil_id: str) -> bool:
        membros = grupo.get("membros")
        if not isinstance(membros, list):
            return False
        return any(
            isinstance(membro, dict) and str(membro.get("perfil_id")) == perfil_id
            for membro in membros
        )

    async def _remover_lugar_dos_guias(self, *, grupo_id: str, lugar_id: str) -> None:
        if not grupo_id:
            return

        guias = await self._client.list_guias(grupo_id=grupo_id)
        for guia in guias:
            if not isinstance(guia, dict):
                continue
            lugar_ids = guia.get("lugar_ids")
            if not isinstance(lugar_ids, list) or lugar_id not in lugar_ids:
                continue
            guia_id = str(guia.get("id", ""))
            if not guia_id:
                continue
            await self._client.update_guia(
                guia_id=guia_id,
                payload={"lugar_ids": [item for item in lugar_ids if item != lugar_id]},
            )

    @classmethod
    def _mapear(cls, raw: dict[str, Any]) -> LugarResponse:
        fotos = cls._parse_fotos(raw.get("fotos"))
        return LugarResponse(
            id=str(raw.get("id", "")),
            grupo_id=str(raw.get("grupo_id", "")),
            nome=str(raw.get("nome", "")),
            categoria=raw.get("categoria"),
            bairro=raw.get("bairro"),
            cidade=raw.get("cidade"),
            faixa_preco=raw.get("faixa_preco"),
            link=raw.get("link"),
            notas=raw.get("notas"),
            status=StatusLugar(raw.get("status") or StatusLugar.QUERO_IR.value),
            favorito=bool(raw.get("favorito") or False),
            imagem_capa=raw.get("imagem_capa"),
            fotos=fotos,
            adicionado_por=raw.get("adicionado_por"),
            adicionado_por_perfil_id=raw.get("adicionado_por_perfil_id"),
            extra=raw.get("extra") or {},
            criado_em=raw.get("criado_em"),
            atualizado_em=raw.get("atualizado_em"),
        )

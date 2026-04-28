from __future__ import annotations

import logging
from typing import Any

from app.core.errors import BadRequestError, NotFoundError
from app.integrations.supabase.client import SupabaseClient
from app.modules.guias.schemas import (
    GuiaCreateRequest,
    GuiaListResponse,
    GuiaLugarRequest,
    GuiaReordenarLugaresRequest,
    GuiaResponse,
    GuiaUpdateRequest,
)
from app.modules.lugares.schemas import LugarResponse
from app.modules.lugares.use_cases import ManageLugaresUseCase

logger = logging.getLogger(__name__)


class ManageGuiasUseCase:
    def __init__(self, client: SupabaseClient) -> None:
        self._client = client

    async def listar(self, *, grupo_id: str) -> GuiaListResponse:
        logger.info("guias.listar.start grupo_id=%s", grupo_id)
        await self._garantir_grupo(grupo_id=grupo_id)
        rows = await self._client.list_guias(grupo_id=grupo_id)
        items = [await self._mapear(row) for row in rows if isinstance(row, dict)]
        logger.info("guias.listar.end grupo_id=%s total=%s", grupo_id, len(items))
        return GuiaListResponse(items=items, total=len(items))

    async def buscar(self, *, guia_id: str) -> GuiaResponse:
        raw = await self._client.get_guia(guia_id=guia_id)
        if raw is None:
            raise NotFoundError("Guia nao encontrado.")
        return await self._mapear(raw)

    async def criar(self, *, request: GuiaCreateRequest) -> GuiaResponse:
        logger.info(
            "guias.criar.start grupo_id=%s nome=%s lugares=%s",
            request.grupo_id,
            request.nome,
            len(request.lugar_ids),
        )
        await self._garantir_grupo(grupo_id=request.grupo_id)
        lugar_ids = await self._validar_lugares_do_grupo(
            grupo_id=request.grupo_id,
            lugar_ids=request.lugar_ids,
        )
        criado = await self._client.insert_guia(
            payload={
                "grupo_id": request.grupo_id,
                "nome": request.nome,
                "descricao": request.descricao,
                "lugar_ids": lugar_ids,
            }
        )
        response = await self._mapear(criado)
        logger.info(
            "guias.criar.end guia_id=%s grupo_id=%s total_lugares=%s",
            response.id,
            response.grupo_id,
            response.total_lugares,
        )
        return response

    async def atualizar(self, *, guia_id: str, request: GuiaUpdateRequest) -> GuiaResponse:
        logger.info(
            "guias.atualizar.start guia_id=%s fields=%s",
            guia_id,
            sorted(request.model_fields_set),
        )
        atual = await self._client.get_guia(guia_id=guia_id)
        if atual is None:
            raise NotFoundError("Guia nao encontrado.")

        payload: dict[str, Any] = {}
        if "nome" in request.model_fields_set:
            payload["nome"] = request.nome
        if "descricao" in request.model_fields_set:
            payload["descricao"] = request.descricao
        if "lugar_ids" in request.model_fields_set:
            payload["lugar_ids"] = await self._validar_lugares_do_grupo(
                grupo_id=str(atual.get("grupo_id", "")),
                lugar_ids=request.lugar_ids or [],
            )

        if not payload:
            raise BadRequestError("Informe ao menos um campo para atualizar.")

        await self._client.update_guia(guia_id=guia_id, payload=payload)
        response = await self.buscar(guia_id=guia_id)
        logger.info("guias.atualizar.end guia_id=%s", guia_id)
        return response

    async def adicionar_lugar(
        self,
        *,
        guia_id: str,
        request: GuiaLugarRequest,
    ) -> GuiaResponse:
        logger.info("guias.adicionar_lugar.start guia_id=%s lugar_id=%s", guia_id, request.lugar_id)
        guia = await self._client.get_guia(guia_id=guia_id)
        if guia is None:
            raise NotFoundError("Guia nao encontrado.")

        lugar_ids = self._parse_lugar_ids(guia.get("lugar_ids"))
        if request.lugar_id not in lugar_ids:
            lugar_ids.append(request.lugar_id)

        lugar_ids = await self._validar_lugares_do_grupo(
            grupo_id=str(guia.get("grupo_id", "")),
            lugar_ids=lugar_ids,
        )
        await self._client.update_guia(
            guia_id=guia_id,
            payload={"lugar_ids": lugar_ids},
        )
        response = await self.buscar(guia_id=guia_id)
        logger.info(
            "guias.adicionar_lugar.end guia_id=%s total_lugares=%s",
            guia_id,
            response.total_lugares,
        )
        return response

    async def remover_lugar(self, *, guia_id: str, lugar_id: str) -> GuiaResponse:
        guia = await self._client.get_guia(guia_id=guia_id)
        if guia is None:
            raise NotFoundError("Guia nao encontrado.")

        lugar_ids = self._parse_lugar_ids(guia.get("lugar_ids"))
        if lugar_id not in lugar_ids:
            raise NotFoundError("Lugar nao esta neste guia.")

        await self._client.update_guia(
            guia_id=guia_id,
            payload={"lugar_ids": [item for item in lugar_ids if item != lugar_id]},
        )
        return await self.buscar(guia_id=guia_id)

    async def reordenar_lugares(
        self,
        *,
        guia_id: str,
        request: GuiaReordenarLugaresRequest,
    ) -> GuiaResponse:
        guia = await self._client.get_guia(guia_id=guia_id)
        if guia is None:
            raise NotFoundError("Guia nao encontrado.")

        atuais = self._parse_lugar_ids(guia.get("lugar_ids"))
        if set(atuais) != set(request.lugar_ids) or len(atuais) != len(request.lugar_ids):
            raise BadRequestError("Envie exatamente os mesmos lugares do guia na nova ordem.")

        await self._client.update_guia(
            guia_id=guia_id,
            payload={"lugar_ids": request.lugar_ids},
        )
        return await self.buscar(guia_id=guia_id)

    async def remover(self, *, guia_id: str) -> dict[str, Any]:
        raw = await self._client.get_guia(guia_id=guia_id)
        if raw is None:
            raise NotFoundError("Guia nao encontrado.")
        await self._client.delete_guia(guia_id=guia_id)
        return {"sucesso": True, "mensagem": "Guia removido com sucesso."}

    async def _garantir_grupo(self, *, grupo_id: str) -> None:
        grupo = await self._client.get_grupo(grupo_id=grupo_id)
        if grupo is None:
            raise NotFoundError("Grupo nao encontrado.")

    async def _validar_lugares_do_grupo(
        self,
        *,
        grupo_id: str,
        lugar_ids: list[str],
    ) -> list[str]:
        normalized = self._parse_lugar_ids(lugar_ids)
        for lugar_id in normalized:
            lugar = await self._client.get_lugar(lugar_id=lugar_id, select="id,grupo_id")
            if lugar is None:
                raise NotFoundError(f"Lugar {lugar_id} nao encontrado.")
            if str(lugar.get("grupo_id", "")) != grupo_id:
                raise BadRequestError("Todos os lugares do guia precisam pertencer ao mesmo grupo.")
        return normalized

    async def _mapear(self, raw: dict[str, Any]) -> GuiaResponse:
        lugar_ids = self._parse_lugar_ids(raw.get("lugar_ids"))
        lugares = await self._carregar_lugares(lugar_ids=lugar_ids)
        lugar_ids = [lugar.id for lugar in lugares]
        return GuiaResponse(
            id=str(raw.get("id", "")),
            grupo_id=str(raw.get("grupo_id", "")),
            nome=str(raw.get("nome", "")),
            descricao=raw.get("descricao"),
            lugar_ids=lugar_ids,
            lugares=lugares,
            total_lugares=len(lugares),
            criado_em=raw.get("criado_em"),
            atualizado_em=raw.get("atualizado_em"),
        )

    async def _carregar_lugares(self, *, lugar_ids: list[str]) -> list[LugarResponse]:
        lugares: list[LugarResponse] = []
        for lugar_id in lugar_ids:
            raw = await self._client.get_lugar(lugar_id=lugar_id, select=ManageLugaresUseCase.SELECT)
            if isinstance(raw, dict):
                lugares.append(ManageLugaresUseCase._mapear(raw))
        return lugares

    @staticmethod
    def _parse_lugar_ids(raw: Any) -> list[str]:
        if not isinstance(raw, list):
            return []
        result: list[str] = []
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, str):
                continue
            normalized = item.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
        return result

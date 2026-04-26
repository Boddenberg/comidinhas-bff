from __future__ import annotations

from typing import Any

from app.core.errors import BadRequestError, NotFoundError
from app.integrations.supabase.client import SupabaseClient
from app.modules.grupos.schemas import (
    GrupoCreateRequest,
    GrupoListResponse,
    GrupoResponse,
    GrupoUpdateRequest,
    MembroSchema,
)


class ManageGruposUseCase:
    def __init__(self, client: SupabaseClient) -> None:
        self._client = client

    async def listar(self) -> GrupoListResponse:
        rows = await self._client.list_grupos()
        items = [self._mapear(r) for r in rows if isinstance(r, dict)]
        return GrupoListResponse(items=items, total=len(items))

    async def buscar(self, *, grupo_id: str) -> GrupoResponse:
        raw = await self._client.get_grupo(grupo_id=grupo_id)
        if raw is None:
            raise NotFoundError("Grupo não encontrado.")
        return self._mapear(raw)

    async def criar(self, *, request: GrupoCreateRequest) -> GrupoResponse:
        payload: dict[str, Any] = {
            "nome": request.nome,
            "tipo": request.tipo,
            "descricao": request.descricao,
            "membros": [m.model_dump() for m in request.membros],
        }
        criado = await self._client.insert_grupo(payload=payload)
        return self._mapear(criado)

    async def atualizar(self, *, grupo_id: str, request: GrupoUpdateRequest) -> GrupoResponse:
        payload = request.model_dump(exclude_unset=True)
        if not payload:
            raise BadRequestError("Informe ao menos um campo para atualizar.")
        if "membros" in payload and payload["membros"] is not None:
            payload["membros"] = [
                m.model_dump() if isinstance(m, MembroSchema) else m
                for m in payload["membros"]
            ]
        await self._client.update_grupo(grupo_id=grupo_id, payload=payload)
        return await self.buscar(grupo_id=grupo_id)

    async def remover(self, *, grupo_id: str) -> dict[str, Any]:
        await self._client.delete_grupo(grupo_id=grupo_id)
        return {"sucesso": True, "mensagem": "Grupo removido com sucesso."}

    @staticmethod
    def _mapear(raw: dict[str, Any]) -> GrupoResponse:
        membros_raw = raw.get("membros") or []
        membros = []
        if isinstance(membros_raw, list):
            for m in membros_raw:
                if isinstance(m, dict):
                    membros.append(MembroSchema(
                        nome=str(m.get("nome", "")),
                        email=m.get("email"),
                    ))
        return GrupoResponse(
            id=str(raw.get("id", "")),
            nome=str(raw.get("nome", "")),
            tipo=str(raw.get("tipo", "casal")),
            descricao=raw.get("descricao"),
            membros=membros,
            criado_em=raw.get("criado_em"),
            atualizado_em=raw.get("atualizado_em"),
        )

from __future__ import annotations

import asyncio
from typing import Any

from app.core.errors import BadRequestError
from app.integrations.supabase.client import SupabaseClient
from app.modules.home.schemas import (
    Contadores,
    GrupoResumo,
    HomeResponse,
    LugarResumo,
)

_STATUS_VISITADO = {"fomos", "quero_voltar", "nao_curti"}


class GetHomeSummaryUseCase:
    def __init__(self, client: SupabaseClient) -> None:
        self._client = client

    async def get_home(self, *, grupo_id: str | None = None, limite: int = 5) -> HomeResponse:
        if not grupo_id:
            raise BadRequestError("Informe o grupo_id.")

        grupo_raw, (rows, _) = await asyncio.gather(
            self._client.get_grupo(grupo_id=grupo_id),
            self._client.list_lugares(
                grupo_id=grupo_id,
                select="*",
                filters=[],
                sort_field="criado_em",
                sort_descending=True,
                page=1,
                page_size=500,
            ),
        )

        grupo = None
        if isinstance(grupo_raw, dict):
            grupo = GrupoResumo(
                id=str(grupo_raw.get("id", "")),
                nome=str(grupo_raw.get("nome", "")),
                tipo=str(grupo_raw.get("tipo", "casal")),
                descricao=grupo_raw.get("descricao"),
                membros=grupo_raw.get("membros") or [],
                criado_em=grupo_raw.get("criado_em"),
                atualizado_em=grupo_raw.get("atualizado_em"),
            )

        contadores = Contadores(
            total=len(rows),
            visitados=sum(1 for r in rows if r.get("status") in _STATUS_VISITADO),
            favoritos=sum(1 for r in rows if r.get("favorito")),
            quero_ir=sum(1 for r in rows if r.get("status") == "quero_ir"),
            quero_voltar=sum(1 for r in rows if r.get("status") == "quero_voltar"),
        )

        def top(predicate=None) -> list[LugarResumo]:
            filtered = [r for r in rows if predicate(r)] if predicate else rows
            return [_mapear(r) for r in filtered[:limite]]

        return HomeResponse(
            grupo=grupo,
            contadores=contadores,
            favoritos=top(lambda r: r.get("favorito")),
            recentes=top(),
            quero_ir=top(lambda r: r.get("status") == "quero_ir"),
            quero_voltar=top(lambda r: r.get("status") == "quero_voltar"),
        )


def _mapear(raw: dict[str, Any]) -> LugarResumo:
    return LugarResumo(
        id=str(raw.get("id", "")),
        nome=str(raw.get("nome", "")),
        categoria=raw.get("categoria"),
        bairro=raw.get("bairro"),
        cidade=raw.get("cidade"),
        faixa_preco=raw.get("faixa_preco"),
        status=raw.get("status"),
        favorito=bool(raw.get("favorito")),
        imagem_capa=raw.get("imagem_capa"),
        adicionado_por=raw.get("adicionado_por"),
        criado_em=raw.get("criado_em"),
    )

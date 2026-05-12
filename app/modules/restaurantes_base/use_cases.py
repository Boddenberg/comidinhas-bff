from __future__ import annotations

import logging
from typing import Any

from app.core.errors import NotFoundError
from app.integrations.supabase.client import SupabaseClient
from app.modules.google_places.place_types import normalize_category_label
from app.modules.lugares.schemas import LugarResponse, StatusLugar
from app.modules.lugares.use_cases import ManageLugaresUseCase
from app.modules.restaurantes_base.repository import BaseRestaurantesRepository
from app.modules.restaurantes_base.schemas import (
    BuscarRestaurantesBaseRequest,
    BuscarRestaurantesBaseResponse,
    SalvarRestauranteBaseRequest,
    RestaurantesBaseStats,
)

logger = logging.getLogger(__name__)


class BuscarRestaurantesBaseUseCase:
    def __init__(self, repository: BaseRestaurantesRepository) -> None:
        self._repository = repository

    async def execute(
        self,
        *,
        request: BuscarRestaurantesBaseRequest,
    ) -> BuscarRestaurantesBaseResponse:
        logger.info(
            "restaurantes_base.buscar.start query_len=%s max_resultados=%s categoria=%s bairro=%s",
            len(request.query),
            request.max_resultados,
            request.categoria,
            request.bairro,
        )
        response = self._repository.buscar(request=request)
        logger.info(
            "restaurantes_base.buscar.end total=%s returned=%s",
            response.total,
            len(response.items),
        )
        return response


class RestaurantesBaseStatsUseCase:
    def __init__(self, repository: BaseRestaurantesRepository) -> None:
        self._repository = repository

    async def execute(self) -> RestaurantesBaseStats:
        return self._repository.stats()


class SalvarRestauranteBaseUseCase:
    def __init__(
        self,
        *,
        repository: BaseRestaurantesRepository,
        supabase_client: SupabaseClient,
    ) -> None:
        self._repository = repository
        self._supabase = supabase_client

    async def execute(self, *, request: SalvarRestauranteBaseRequest) -> LugarResponse:
        restaurante = self._repository.buscar_por_id(request.restaurante_id)
        if restaurante is None:
            raise NotFoundError("Restaurante da base nao encontrado.")

        payload: dict[str, Any] = {
            "grupo_id": request.grupo_id,
            "nome": restaurante.nome,
            "categoria": normalize_category_label(restaurante.tipo or restaurante.categoria),
            "bairro": restaurante.bairro,
            "cidade": restaurante.cidade,
            "link": None,
            "notas": request.notas or restaurante.descricao,
            "status": request.status.value
            if isinstance(request.status, StatusLugar)
            else request.status,
            "favorito": request.favorito,
            "adicionado_por": request.adicionado_por,
            "adicionado_por_perfil_id": request.adicionado_por_perfil_id,
            "extra": {
                "source": "base_conhecimento",
                "base_restaurante_id": restaurante.id,
                "base_categoria_id": restaurante.categoria_id,
                "base_categoria": restaurante.categoria,
                "base_tipo": restaurante.tipo,
                "base_endereco": restaurante.endereco,
                "base_distincao": restaurante.distincao,
                "base_fonte_chunk": restaurante.fonte_chunk,
                "base_descricao": restaurante.descricao,
            },
        }

        lugares_use_case = ManageLugaresUseCase(self._supabase)
        await lugares_use_case._preparar_autor(
            payload=payload,
            grupo_id=request.grupo_id,
        )
        created = await self._supabase.insert_lugar(payload=payload)
        return ManageLugaresUseCase._mapear(created)

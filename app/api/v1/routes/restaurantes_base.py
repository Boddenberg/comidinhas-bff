from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import (
    get_buscar_restaurantes_base_use_case,
    get_restaurantes_base_stats_use_case,
    get_salvar_restaurante_base_use_case,
)
from app.modules.restaurantes_base.schemas import (
    BuscarRestaurantesBaseRequest,
    BuscarRestaurantesBaseResponse,
    SalvarRestauranteBaseRequest,
    RestaurantesBaseStats,
)
from app.modules.restaurantes_base.use_cases import (
    BuscarRestaurantesBaseUseCase,
    SalvarRestauranteBaseUseCase,
    RestaurantesBaseStatsUseCase,
)
from app.modules.lugares.schemas import LugarResponse

router = APIRouter(prefix="/restaurantes-base", tags=["restaurantes-base"])


@router.get(
    "/stats",
    response_model=RestaurantesBaseStats,
    summary="Resumo da base local de restaurantes",
)
async def stats_restaurantes_base(
    use_case: RestaurantesBaseStatsUseCase = Depends(get_restaurantes_base_stats_use_case),
) -> RestaurantesBaseStats:
    return await use_case.execute()


@router.get(
    "/buscar",
    response_model=BuscarRestaurantesBaseResponse,
    summary="Busca restaurantes na base local sem provedores externos",
)
async def buscar_restaurantes_base(
    query: str = Query(..., min_length=1, max_length=300),
    categoria: str | None = Query(default=None, max_length=120),
    bairro: str | None = Query(default=None, max_length=80),
    max_resultados: int = Query(default=10, ge=1, le=50),
    incluir_markdown: bool = Query(default=False),
    use_case: BuscarRestaurantesBaseUseCase = Depends(get_buscar_restaurantes_base_use_case),
) -> BuscarRestaurantesBaseResponse:
    request = BuscarRestaurantesBaseRequest(
        query=query,
        categoria=categoria,
        bairro=bairro,
        max_resultados=max_resultados,
        incluir_markdown=incluir_markdown,
    )
    return await use_case.execute(request=request)


@router.post(
    "/salvar",
    response_model=LugarResponse,
    status_code=201,
    summary="Salva um restaurante da base local como lugar do grupo",
)
async def salvar_restaurante_base(
    request: SalvarRestauranteBaseRequest,
    use_case: SalvarRestauranteBaseUseCase = Depends(get_salvar_restaurante_base_use_case),
) -> LugarResponse:
    return await use_case.execute(request=request)

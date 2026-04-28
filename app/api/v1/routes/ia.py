from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import (
    get_decidir_restaurante_use_case,
    get_recomendar_restaurantes_use_case,
)
from app.modules.decisoes.recomendacoes import RecomendarRestaurantesUseCase
from app.modules.decisoes.schemas import (
    DecidirRestauranteRequest,
    DecidirRestauranteResponse,
    RecomendarRestaurantesRequest,
    RecomendarRestaurantesResponse,
)
from app.modules.decisoes.use_cases import DecidirRestauranteUseCase

router = APIRouter(prefix="/ia", tags=["ia"])


@router.post(
    "/decidir-restaurante",
    response_model=DecidirRestauranteResponse,
    summary="Deixa a IA escolher um restaurante dentro de um escopo",
)
async def decidir_restaurante(
    request: DecidirRestauranteRequest,
    use_case: DecidirRestauranteUseCase = Depends(get_decidir_restaurante_use_case),
) -> DecidirRestauranteResponse:
    return await use_case.execute(request=request)


@router.post(
    "/recomendar-restaurantes",
    response_model=RecomendarRestaurantesResponse,
    summary="Recomenda restaurantes a partir de uma mensagem em linguagem natural",
)
async def recomendar_restaurantes(
    request: RecomendarRestaurantesRequest,
    use_case: RecomendarRestaurantesUseCase = Depends(get_recomendar_restaurantes_use_case),
) -> RecomendarRestaurantesResponse:
    return await use_case.execute(request=request)

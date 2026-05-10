from __future__ import annotations

from fastapi import APIRouter, Depends, Path

from app.api.dependencies import (
    get_decidir_restaurante_use_case,
    get_recomendar_restaurantes_use_case,
    get_registrar_feedback_sugestao_use_case,
)
from app.modules.decisoes.feedback_use_case import RegistrarFeedbackSugestaoUseCase
from app.modules.decisoes.recomendacoes import RecomendarRestaurantesUseCase
from app.modules.decisoes.schemas import (
    DecidirRestauranteRequest,
    DecidirRestauranteResponse,
    RecomendarRestaurantesRequest,
    RecomendarRestaurantesResponse,
    SugestaoFeedbackRequest,
    SugestaoFeedbackResponse,
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


@router.post(
    "/sugestoes/{sugestao_id}/feedback",
    response_model=SugestaoFeedbackResponse,
    summary="Registra feedback do usuario sobre uma sugestao da IA",
)
async def registrar_feedback_sugestao(
    request: SugestaoFeedbackRequest,
    sugestao_id: str = Path(..., min_length=8, max_length=64),
    use_case: RegistrarFeedbackSugestaoUseCase = Depends(
        get_registrar_feedback_sugestao_use_case
    ),
) -> SugestaoFeedbackResponse:
    return await use_case.execute(sugestao_id=sugestao_id, request=request)

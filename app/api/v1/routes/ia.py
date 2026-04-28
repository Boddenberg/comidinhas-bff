from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import get_decidir_restaurante_use_case
from app.modules.decisoes.schemas import (
    DecidirRestauranteRequest,
    DecidirRestauranteResponse,
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

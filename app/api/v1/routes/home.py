from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_home_use_case
from app.modules.home.schemas import HomeResponse
from app.modules.home.use_cases import GetHomeSummaryUseCase

router = APIRouter(prefix="/home", tags=["home"])


@router.get(
    "/",
    response_model=HomeResponse,
    summary="Retorna o agregado da home: grupo, contadores, favoritos, recentes e filas",
)
async def get_home(
    grupo_id: str = Query(..., description="UUID do grupo"),
    limite: int = Query(
        default=5,
        ge=1,
        le=20,
        description="Quantidade de itens em cada lista da home",
    ),
    use_case: GetHomeSummaryUseCase = Depends(get_home_use_case),
) -> HomeResponse:
    return await use_case.get_home(grupo_id=grupo_id, limite=limite)

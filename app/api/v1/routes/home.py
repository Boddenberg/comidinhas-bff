from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_home_use_case
from app.api.v1.routes.profiles import get_access_token
from app.modules.home.schemas import HomeResponse
from app.modules.home.use_cases import GetHomeSummaryUseCase

router = APIRouter(prefix="/home", tags=["home"])


@router.get(
    "/",
    response_model=HomeResponse,
    summary="Retorna o agregado da home: grupo, contadores, favoritos, ultimos e filas",
)
async def get_home(
    group_id: str | None = Query(
        default=None,
        description="UUID do grupo. Se omitido, usa o grupo ativo do usuario.",
    ),
    top_limit: int = Query(
        default=5,
        ge=1,
        le=20,
        description="Quantidade de itens em cada lista da home",
    ),
    access_token: str = Depends(get_access_token),
    use_case: GetHomeSummaryUseCase = Depends(get_home_use_case),
) -> HomeResponse:
    return await use_case.get_home(
        access_token=access_token,
        group_id=group_id,
        top_limit=top_limit,
    )

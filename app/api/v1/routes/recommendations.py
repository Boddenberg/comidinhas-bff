from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import get_today_recommendations_use_case
from app.modules.decisoes.schemas import TodayRecommendationsRequest, TodayRecommendationsResponse
from app.modules.decisoes.today_recommendations import TodayRecommendationsUseCase

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.post(
    "/today",
    response_model=TodayRecommendationsResponse,
    summary="Recomenda tres restaurantes novos para a Home",
)
async def today_recommendations(
    request: TodayRecommendationsRequest,
    use_case: TodayRecommendationsUseCase = Depends(get_today_recommendations_use_case),
) -> TodayRecommendationsResponse:
    return await use_case.execute(request=request)

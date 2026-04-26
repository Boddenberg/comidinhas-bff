from fastapi import APIRouter, Depends

from app.api.dependencies import get_nearby_restaurants_use_case
from app.modules.google_places.schemas import (
    NearbyRestaurantsRequest,
    NearbyRestaurantsResponse,
)
from app.modules.google_places.use_cases import SearchNearbyRestaurantsUseCase

router = APIRouter(prefix="/google-maps", tags=["google-maps"])


@router.post(
    "/restaurants/nearby",
    response_model=NearbyRestaurantsResponse,
    summary="Busca restaurantes proximos usando Google Places",
)
async def search_nearby_restaurants(
    request: NearbyRestaurantsRequest,
    use_case: SearchNearbyRestaurantsUseCase = Depends(
        get_nearby_restaurants_use_case,
    ),
) -> NearbyRestaurantsResponse:
    return await use_case.execute(request)

from __future__ import annotations

from fastapi import APIRouter, Depends, Path

from app.api.dependencies import (
    get_autocomplete_use_case,
    get_nearby_restaurants_use_case,
    get_place_details_use_case,
    get_save_from_google_use_case,
)
from app.api.v1.routes.profiles import get_access_token
from app.modules.google_places.schemas import (
    NearbyRestaurantsRequest,
    NearbyRestaurantsResponse,
    PlaceAutocompleteRequest,
    PlaceAutocompleteResponse,
    PlaceDetailsResponse,
    SaveFromGoogleRequest,
)
from app.modules.google_places.use_cases import (
    AutocompletePlacesUseCase,
    GetPlaceDetailsUseCase,
    SavePlaceFromGoogleUseCase,
    SearchNearbyRestaurantsUseCase,
)
from app.modules.places.schemas import PlaceResponse

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


@router.post(
    "/places/autocomplete",
    response_model=PlaceAutocompleteResponse,
    summary="Sugestoes de lugares enquanto o usuario digita (Place Autocomplete)",
)
async def autocomplete_places(
    request: PlaceAutocompleteRequest,
    use_case: AutocompletePlacesUseCase = Depends(get_autocomplete_use_case),
) -> PlaceAutocompleteResponse:
    return await use_case.execute(request)


@router.get(
    "/places/{place_id}",
    response_model=PlaceDetailsResponse,
    summary="Detalhes completos de um lugar pelo Google Place ID",
)
async def get_place_details(
    place_id: str = Path(..., min_length=4, max_length=500),
    use_case: GetPlaceDetailsUseCase = Depends(get_place_details_use_case),
) -> PlaceDetailsResponse:
    return await use_case.execute(place_id)


@router.post(
    "/places/save",
    response_model=PlaceResponse,
    status_code=201,
    summary="Busca detalhes no Google Places e salva o lugar no banco de dados do grupo",
)
async def save_place_from_google(
    request: SaveFromGoogleRequest,
    access_token: str = Depends(get_access_token),
    use_case: SavePlaceFromGoogleUseCase = Depends(get_save_from_google_use_case),
) -> PlaceResponse:
    return await use_case.execute(access_token=access_token, request=request)

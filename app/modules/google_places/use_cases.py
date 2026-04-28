from __future__ import annotations

from app.integrations.google_places.client import GooglePlacesClient
from app.integrations.supabase.client import SupabaseClient
from app.modules.google_places.schemas import (
    NearbyRestaurantsRequest,
    NearbyRestaurantsResponse,
    PlaceAutocompleteRequest,
    PlaceAutocompleteResponse,
    PlaceDetailsResponse,
    SaveFromGoogleRequest,
)
from app.modules.lugares.schemas import LugarResponse
from app.modules.lugares.use_cases import ManageLugaresUseCase


class SearchNearbyRestaurantsUseCase:
    def __init__(self, client: GooglePlacesClient) -> None:
        self._client = client

    async def execute(
        self,
        request: NearbyRestaurantsRequest,
    ) -> NearbyRestaurantsResponse:
        places = await self._client.search_nearby_restaurants(request)
        return NearbyRestaurantsResponse(places=places)


class AutocompletePlacesUseCase:
    def __init__(self, client: GooglePlacesClient) -> None:
        self._client = client

    async def execute(
        self,
        request: PlaceAutocompleteRequest,
    ) -> PlaceAutocompleteResponse:
        return await self._client.autocomplete(request)


class GetPlaceDetailsUseCase:
    def __init__(self, client: GooglePlacesClient) -> None:
        self._client = client

    async def execute(self, place_id: str) -> PlaceDetailsResponse:
        return await self._client.get_place_details(place_id)


class SavePlaceFromGoogleUseCase:
    def __init__(
        self,
        google_client: GooglePlacesClient,
        supabase_client: SupabaseClient,
    ) -> None:
        self._google = google_client
        self._supabase = supabase_client

    async def execute(self, *, request: SaveFromGoogleRequest) -> LugarResponse:
        raw = await self._google.get_place_details_raw(request.place_id)
        details = self._google._map_place_details(raw, place_id=request.place_id)

        photo_name = self._google._extract_string(
            (raw.get("photos") or [{}])[0] if raw.get("photos") else {},
            "name",
        )
        photo_uri = await self._google._fetch_photo_uri(photo_name)

        payload = {
            "grupo_id": request.grupo_id,
            "nome": details.display_name or request.place_id,
            "categoria": details.primary_type_display_name or details.primary_type,
            "bairro": details.neighborhood,
            "cidade": details.city,
            "faixa_preco": details.price_range,
            "link": details.google_maps_uri or details.website_uri,
            "imagem_capa": photo_uri,
            "notas": request.notas,
            "status": request.status,
            "favorito": request.favorito,
            "adicionado_por": request.adicionado_por,
            "extra": {
                "google_place_id": request.place_id,
                "formatted_address": details.formatted_address,
                "rating": details.rating,
                "user_rating_count": details.user_rating_count,
                "website_uri": details.website_uri,
                "phone_number": details.phone_number,
                "open_now": details.open_now,
                "types": details.types,
            },
        }

        created = await self._supabase.insert_lugar(payload=payload)
        return ManageLugaresUseCase._mapear(created)

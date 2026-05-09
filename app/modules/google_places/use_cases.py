from __future__ import annotations

import logging

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
from app.modules.google_places.place_types import friendly_place_type
from app.modules.lugares.schemas import LugarResponse
from app.modules.lugares.use_cases import ManageLugaresUseCase

logger = logging.getLogger(__name__)


class SearchNearbyRestaurantsUseCase:
    def __init__(self, client: GooglePlacesClient) -> None:
        self._client = client

    async def execute(
        self,
        request: NearbyRestaurantsRequest,
    ) -> NearbyRestaurantsResponse:
        logger.info(
            "google_places.use_case.search_nearby.start lat=%s lng=%s radius=%s max_results=%s",
            request.latitude,
            request.longitude,
            request.radius_meters,
            request.max_results,
        )
        places = await self._client.search_nearby_restaurants(request)
        logger.info(
            "google_places.use_case.search_nearby.end total=%s",
            len(places),
        )
        return NearbyRestaurantsResponse(places=places)


class AutocompletePlacesUseCase:
    def __init__(self, client: GooglePlacesClient) -> None:
        self._client = client

    async def execute(
        self,
        request: PlaceAutocompleteRequest,
    ) -> PlaceAutocompleteResponse:
        logger.info(
            "google_places.use_case.autocomplete.start input_len=%s max_results=%s",
            len(request.input),
            request.max_results,
        )
        response = await self._client.autocomplete(request)
        logger.info(
            "google_places.use_case.autocomplete.end suggestions=%s",
            len(response.suggestions),
        )
        return response


class GetPlaceDetailsUseCase:
    def __init__(self, client: GooglePlacesClient) -> None:
        self._client = client

    async def execute(self, place_id: str) -> PlaceDetailsResponse:
        logger.info("google_places.use_case.details.start place_id=%s", place_id)
        response = await self._client.get_place_details(place_id)
        logger.info(
            "google_places.use_case.details.end place_id=%s has_maps=%s has_photo=%s",
            place_id,
            bool(response.google_maps_uri),
            bool(response.photo_uri),
        )
        return response


class SavePlaceFromGoogleUseCase:
    def __init__(
        self,
        google_client: GooglePlacesClient,
        supabase_client: SupabaseClient,
    ) -> None:
        self._google = google_client
        self._supabase = supabase_client

    async def execute(self, *, request: SaveFromGoogleRequest) -> LugarResponse:
        logger.info(
            "google_places.use_case.save.start place_id=%s grupo_id=%s status=%s favorito=%s",
            request.place_id,
            request.grupo_id,
            request.status,
            request.favorito,
        )
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
            "categoria": friendly_place_type(
                details.primary_type,
                details.primary_type_display_name,
            ),
            "bairro": details.neighborhood,
            "cidade": details.city,
            "faixa_preco": details.price_range,
            "link": details.google_maps_uri or details.website_uri,
            "imagem_capa": photo_uri,
            "notas": request.notas,
            "status": request.status,
            "favorito": request.favorito,
            "adicionado_por": request.adicionado_por,
            "adicionado_por_perfil_id": request.adicionado_por_perfil_id,
            "extra": {
                "google_place_id": request.place_id,
                "formatted_address": details.formatted_address,
                "rating": details.rating,
                "user_rating_count": details.user_rating_count,
                "website_uri": details.website_uri,
                "phone_number": details.phone_number,
                "open_now": details.open_now,
                "primary_type": details.primary_type,
                "primary_type_display_name": details.primary_type_display_name,
                "types": details.types,
            },
        }

        lugares_use_case = ManageLugaresUseCase(self._supabase)
        await lugares_use_case._preparar_autor(payload=payload, grupo_id=request.grupo_id)

        created = await self._supabase.insert_lugar(payload=payload)
        response = ManageLugaresUseCase._mapear(created)
        logger.info(
            "google_places.use_case.save.end place_id=%s lugar_id=%s grupo_id=%s has_photo=%s",
            request.place_id,
            response.id,
            response.grupo_id,
            bool(response.imagem_capa),
        )
        return response

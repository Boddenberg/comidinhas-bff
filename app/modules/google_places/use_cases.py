from __future__ import annotations

from typing import Any

from app.core.errors import BadRequestError
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
from app.modules.places.schemas import PlaceResponse, PlaceStatus
from app.modules.places.use_cases import ManagePlacesUseCase


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
        details = await self._client.get_place_details(place_id)
        photo_uri = await self._client._fetch_photo_uri(
            await self._extract_first_photo_name(self._client, place_id),
        )
        return details.model_copy(update={"photo_uri": photo_uri})

    @staticmethod
    async def _extract_first_photo_name(
        client: GooglePlacesClient,
        place_id: str,
    ) -> str | None:
        try:
            raw = await client.get_place_details_raw(place_id)
            photos = raw.get("photos")
            if isinstance(photos, list) and photos:
                first = photos[0]
                if isinstance(first, dict):
                    return client._extract_string(first, "name")
        except Exception:
            pass
        return None


class SavePlaceFromGoogleUseCase:
    def __init__(
        self,
        google_client: GooglePlacesClient,
        supabase_client: SupabaseClient,
    ) -> None:
        self._google = google_client
        self._supabase = supabase_client

    async def execute(
        self,
        *,
        access_token: str,
        request: SaveFromGoogleRequest,
    ) -> PlaceResponse:
        try:
            status = PlaceStatus(request.status)
        except ValueError:
            raise BadRequestError(
                f"Status invalido: {request.status!r}. "
                f"Use: quero_ir, fomos, quero_voltar, nao_curti."
            )

        raw = await self._google.get_place_details_raw(request.place_id)
        details = self._google._map_place_details(raw, place_id=request.place_id)

        photo_name = self._google._extract_string(
            (raw.get("photos") or [{}])[0] if raw.get("photos") else {},
            "name",
        )
        photo_uri = await self._google._fetch_photo_uri(photo_name)

        group_id = await self._resolve_group_id(
            access_token=access_token,
            group_id=request.group_id,
        )

        user_payload = await self._supabase.get_user(access_token=access_token)
        creator_id = str(user_payload["id"])

        payload: dict[str, Any] = {
            "group_id": group_id,
            "name": details.display_name or request.place_id,
            "category": details.primary_type_display_name or details.primary_type,
            "neighborhood": details.neighborhood,
            "city": details.city,
            "price_range": details.price_range,
            "link": details.google_maps_uri or details.website_uri,
            "image_url": photo_uri,
            "notes": request.notes,
            "status": status.value,
            "is_favorite": request.is_favorite,
            "created_by": creator_id,
            "extra_data": {
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

        created = await self._supabase.insert_place(
            access_token=access_token,
            payload=payload,
        )

        places_uc = ManagePlacesUseCase(self._supabase)
        return await places_uc.get_place(
            access_token=access_token,
            place_id=str(created["id"]),
        )

    async def _resolve_group_id(
        self,
        *,
        access_token: str,
        group_id: str | None,
    ) -> str:
        if group_id:
            return group_id
        user_payload = await self._supabase.get_user(access_token=access_token)
        profile = await self._supabase.get_profile(
            access_token=access_token,
            user_id=str(user_payload["id"]),
        )
        if isinstance(profile, dict):
            active_group_id = profile.get("active_group_id")
            if isinstance(active_group_id, str) and active_group_id:
                return active_group_id
        raise BadRequestError(
            "Voce ainda nao tem um grupo ativo. Informe group_id ou configure um grupo ativo.",
        )

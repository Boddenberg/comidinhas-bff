import asyncio
from typing import Any

import httpx

from app.core.config import Settings
from app.core.errors import ConfigurationError, ExternalServiceError
from app.modules.google_places.schemas import (
    NearbyRestaurant,
    NearbyRestaurantsRequest,
    PhotoAttribution,
    RestaurantLocation,
)


class GooglePlacesClient:
    SEARCH_FIELD_MASK = ",".join(
        [
            "places.id",
            "places.displayName",
            "places.formattedAddress",
            "places.location",
            "places.rating",
            "places.userRatingCount",
            "places.priceLevel",
            "places.primaryType",
            "places.googleMapsUri",
            "places.websiteUri",
            "places.nationalPhoneNumber",
            "places.regularOpeningHours.openNow",
            "places.photos",
        ]
    )

    def __init__(self, http_client: httpx.AsyncClient, settings: Settings) -> None:
        self._http_client = http_client
        self._settings = settings

    async def search_nearby_restaurants(
        self,
        request: NearbyRestaurantsRequest,
    ) -> list[NearbyRestaurant]:
        self._ensure_api_key()

        payload = self._build_search_payload(request)
        raw_places = await self._search_nearby(payload)
        places = [self._map_place(place) for place in raw_places]

        photo_uris = await asyncio.gather(
            *(self._fetch_photo_uri(place.photo_name) for place in places)
        )

        return [
            place.model_copy(update={"photo_uri": photo_uri})
            for place, photo_uri in zip(places, photo_uris, strict=True)
        ]

    def _ensure_api_key(self) -> None:
        if self._settings.is_google_places_configured:
            return

        raise ConfigurationError(
            "Configure GOOGLE_MAPS_API_KEY no arquivo .env ou nas variaveis de ambiente.",
        )

    async def _search_nearby(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            response = await self._http_client.post(
                f"{self._settings.google_places_base_url}/places:searchNearby",
                headers={
                    "Content-Type": "application/json",
                    "X-Goog-Api-Key": self._settings.google_maps_api_key or "",
                    "X-Goog-FieldMask": self.SEARCH_FIELD_MASK,
                },
                json=payload,
                timeout=self._settings.google_places_timeout_seconds,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ExternalServiceError(
                "google_places",
                "Timeout ao chamar o Google Places.",
            ) from exc
        except httpx.HTTPStatusError as exc:
            message = self._extract_error_message(exc.response)
            raise ExternalServiceError(
                "google_places",
                f"Falha ao chamar o Google Places: {message}",
            ) from exc
        except httpx.HTTPError as exc:
            raise ExternalServiceError(
                "google_places",
                "Erro de rede ao chamar o Google Places.",
            ) from exc

        payload = response.json()
        places = payload.get("places", [])
        if isinstance(places, list):
            return [place for place in places if isinstance(place, dict)]
        return []

    def _build_search_payload(
        self,
        request: NearbyRestaurantsRequest,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "includedTypes": request.included_types,
            "maxResultCount": request.max_results,
            "locationRestriction": {
                "circle": {
                    "center": {
                        "latitude": request.latitude,
                        "longitude": request.longitude,
                    },
                    "radius": float(request.radius_meters),
                }
            },
            "rankPreference": request.rank_preference.value,
            "languageCode": request.language_code
            or self._settings.google_places_default_language_code,
            "regionCode": request.region_code
            or self._settings.google_places_default_region_code,
        }

        if request.excluded_types:
            payload["excludedTypes"] = request.excluded_types

        return payload

    def _map_place(self, payload: dict[str, Any]) -> NearbyRestaurant:
        location = payload.get("location")
        photo = self._extract_first_photo(payload)

        return NearbyRestaurant(
            id=str(payload.get("id", "")),
            display_name=self._extract_display_name(payload),
            formatted_address=self._extract_string(payload, "formattedAddress"),
            location=self._map_location(location),
            rating=self._extract_float(payload, "rating"),
            user_rating_count=self._extract_int(payload, "userRatingCount"),
            price_level=self._extract_string(payload, "priceLevel"),
            primary_type=self._extract_string(payload, "primaryType"),
            google_maps_uri=self._extract_string(payload, "googleMapsUri"),
            website_uri=self._extract_string(payload, "websiteUri"),
            phone_number=self._extract_string(payload, "nationalPhoneNumber"),
            open_now=self._extract_open_now(payload),
            photo_name=self._extract_string(photo, "name") if photo else None,
            photo_attributions=self._extract_photo_attributions(photo),
        )

    @staticmethod
    def _extract_display_name(payload: dict[str, Any]) -> str:
        display_name = payload.get("displayName")
        if isinstance(display_name, dict):
            text = display_name.get("text")
            if isinstance(text, str):
                return text
        return ""

    @staticmethod
    def _extract_first_photo(payload: dict[str, Any]) -> dict[str, Any] | None:
        photos = payload.get("photos")
        if not isinstance(photos, list) or not photos:
            return None

        first_photo = photos[0]
        if isinstance(first_photo, dict):
            return first_photo
        return None

    @staticmethod
    def _extract_photo_attributions(
        photo: dict[str, Any] | None,
    ) -> list[PhotoAttribution]:
        if photo is None:
            return []

        raw_attributions = photo.get("authorAttributions")
        if not isinstance(raw_attributions, list):
            return []

        attributions: list[PhotoAttribution] = []
        for item in raw_attributions:
            if not isinstance(item, dict):
                continue

            attributions.append(
                PhotoAttribution(
                    display_name=GooglePlacesClient._extract_string(item, "displayName"),
                    uri=GooglePlacesClient._extract_string(item, "uri"),
                    photo_uri=GooglePlacesClient._extract_string(item, "photoUri"),
                )
            )

        return attributions

    @staticmethod
    def _map_location(location: Any) -> RestaurantLocation | None:
        if not isinstance(location, dict):
            return None

        latitude = location.get("latitude")
        longitude = location.get("longitude")
        if not isinstance(latitude, (int, float)) or not isinstance(
            longitude,
            (int, float),
        ):
            return None

        return RestaurantLocation(latitude=latitude, longitude=longitude)

    @staticmethod
    def _extract_open_now(payload: dict[str, Any]) -> bool | None:
        opening_hours = payload.get("regularOpeningHours")
        if not isinstance(opening_hours, dict):
            return None

        open_now = opening_hours.get("openNow")
        if isinstance(open_now, bool):
            return open_now

        return None

    @staticmethod
    def _extract_string(payload: dict[str, Any] | None, key: str) -> str | None:
        if not isinstance(payload, dict):
            return None

        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value

        return None

    @staticmethod
    def _extract_float(payload: dict[str, Any], key: str) -> float | None:
        value = payload.get(key)
        if isinstance(value, (int, float)):
            return float(value)
        return None

    @staticmethod
    def _extract_int(payload: dict[str, Any], key: str) -> int | None:
        value = payload.get(key)
        if isinstance(value, int):
            return value
        return None

    async def _fetch_photo_uri(self, photo_name: str | None) -> str | None:
        if not photo_name:
            return None

        try:
            response = await self._http_client.get(
                f"{self._settings.google_places_base_url}/{photo_name}/media",
                params={
                    "key": self._settings.google_maps_api_key,
                    "maxWidthPx": self._settings.google_places_photo_max_width,
                    "maxHeightPx": self._settings.google_places_photo_max_height,
                    "skipHttpRedirect": "true",
                },
                timeout=self._settings.google_places_timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError:
            return None

        payload = response.json()
        photo_uri = payload.get("photoUri")
        if isinstance(photo_uri, str) and photo_uri.strip():
            return photo_uri
        return None

    @staticmethod
    def _extract_error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            payload = None

        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                message = error.get("message")
                if isinstance(message, str) and message.strip():
                    return message.strip()

        return f"HTTP {response.status_code}"

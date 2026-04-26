import asyncio
from typing import Any

import httpx

from app.core.config import Settings
from app.core.errors import ConfigurationError, ExternalServiceError
from app.modules.google_places.schemas import (
    LocationBias,
    MatchedSubstring,
    NearbyRestaurant,
    NearbyRestaurantsRequest,
    PhotoAttribution,
    PlaceAutocompleteRequest,
    PlaceAutocompleteResponse,
    PlaceDetailsLocation,
    PlaceDetailsResponse,
    PlacePrediction,
    PredictionText,
    QueryPrediction,
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

    AUTOCOMPLETE_URL = "places:autocomplete"
    DETAILS_FIELD_MASK = ",".join(
        [
            "id",
            "displayName",
            "formattedAddress",
            "location",
            "rating",
            "userRatingCount",
            "priceLevel",
            "primaryType",
            "primaryTypeDisplayName",
            "googleMapsUri",
            "websiteUri",
            "nationalPhoneNumber",
            "regularOpeningHours.openNow",
            "photos",
            "types",
            "addressComponents",
        ]
    )

    # ---------------------------------------------------------------- autocomplete

    async def autocomplete(
        self,
        request: PlaceAutocompleteRequest,
    ) -> PlaceAutocompleteResponse:
        self._ensure_api_key()

        body: dict[str, Any] = {
            "input": request.input,
            "languageCode": request.language_code
            or self._settings.google_places_default_language_code,
            "regionCode": self._settings.google_places_default_region_code,
            "includeQueryPredictions": request.include_query_predictions,
        }

        if request.included_primary_types:
            body["includedPrimaryTypes"] = request.included_primary_types

        if request.included_region_codes:
            body["includedRegionCodes"] = request.included_region_codes

        if request.session_token:
            body["sessionToken"] = request.session_token

        if request.location_bias:
            body["locationBias"] = self._build_circle(request.location_bias)

        if request.location_restriction:
            body["locationRestriction"] = self._build_circle(
                request.location_restriction,
            )

        raw = await self._post_json(
            self.AUTOCOMPLETE_URL,
            body=body,
            field_mask=None,
        )

        suggestions_raw = raw.get("suggestions") or []
        suggestions: list[PlacePrediction | QueryPrediction] = []

        for item in suggestions_raw[:request.max_results]:
            if not isinstance(item, dict):
                continue
            if "placePrediction" in item:
                prediction = self._map_place_prediction(item["placePrediction"])
                if prediction:
                    suggestions.append(prediction)
            elif "queryPrediction" in item:
                prediction = self._map_query_prediction(item["queryPrediction"])
                if prediction:
                    suggestions.append(prediction)

        return PlaceAutocompleteResponse(suggestions=suggestions)

    # ---------------------------------------------------------------- place details

    async def get_place_details(
        self,
        place_id: str,
    ) -> PlaceDetailsResponse:
        self._ensure_api_key()
        raw = await self._get_json(f"places/{place_id}", field_mask=self.DETAILS_FIELD_MASK)
        return self._map_place_details(raw, place_id=place_id)

    async def get_place_details_raw(self, place_id: str) -> dict[str, Any]:
        self._ensure_api_key()
        return await self._get_json(f"places/{place_id}", field_mask=self.DETAILS_FIELD_MASK)

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _build_circle(bias: LocationBias) -> dict[str, Any]:
        return {
            "circle": {
                "center": {
                    "latitude": bias.latitude,
                    "longitude": bias.longitude,
                },
                "radius": float(bias.radius_meters),
            }
        }

    def _map_place_prediction(
        self, raw: dict[str, Any]
    ) -> PlacePrediction | None:
        place_id = raw.get("placeId")
        if not isinstance(place_id, str) or not place_id:
            return None

        text_raw = raw.get("text") or {}
        structured = raw.get("structuredFormat") or {}

        return PlacePrediction(
            place_id=place_id,
            text=self._map_prediction_text(text_raw),
            main_text=self._map_prediction_text(structured.get("mainText")),
            secondary_text=self._map_prediction_text(structured.get("secondaryText")),
            types=raw.get("types") or [],
            distance_meters=raw.get("distanceMeters"),
        )

    def _map_query_prediction(
        self, raw: dict[str, Any]
    ) -> QueryPrediction | None:
        text_raw = raw.get("text")
        if not isinstance(text_raw, dict):
            return None

        structured = raw.get("structuredFormat") or {}
        return QueryPrediction(
            text=self._map_prediction_text(text_raw),
            main_text=self._map_prediction_text(structured.get("mainText")),
            secondary_text=self._map_prediction_text(structured.get("secondaryText")),
        )

    @staticmethod
    def _map_prediction_text(raw: Any) -> PredictionText:
        if not isinstance(raw, dict):
            return PredictionText(text="")
        text = raw.get("text") or ""
        matches_raw = raw.get("matches") or []
        matches = [
            MatchedSubstring(
                start_offset=int(m.get("startOffset") or 0),
                end_offset=int(m.get("endOffset") or 0),
            )
            for m in matches_raw
            if isinstance(m, dict)
        ]
        return PredictionText(text=text, matches=matches)

    def _map_place_details(
        self,
        raw: dict[str, Any],
        *,
        place_id: str,
    ) -> PlaceDetailsResponse:
        neighborhood, city = self._extract_address_components(
            raw.get("addressComponents") or [],
        )
        photo = self._extract_first_photo(raw)

        primary_type_name = raw.get("primaryTypeDisplayName")
        if isinstance(primary_type_name, dict):
            primary_type_name = primary_type_name.get("text")

        return PlaceDetailsResponse(
            place_id=place_id,
            display_name=self._extract_display_name(raw),
            formatted_address=self._extract_string(raw, "formattedAddress"),
            location=self._map_details_location(raw.get("location")),
            neighborhood=neighborhood,
            city=city,
            rating=self._extract_float(raw, "rating"),
            user_rating_count=self._extract_int(raw, "userRatingCount"),
            price_level=self._extract_string(raw, "priceLevel"),
            price_range=self._map_price_level(raw.get("priceLevel")),
            primary_type=self._extract_string(raw, "primaryType"),
            primary_type_display_name=primary_type_name if isinstance(primary_type_name, str) else None,
            google_maps_uri=self._extract_string(raw, "googleMapsUri"),
            website_uri=self._extract_string(raw, "websiteUri"),
            phone_number=self._extract_string(raw, "nationalPhoneNumber"),
            open_now=self._extract_open_now(raw),
            photo_uri=None,
            types=raw.get("types") or [],
        )

    @staticmethod
    def _extract_address_components(
        components: list[Any],
    ) -> tuple[str | None, str | None]:
        neighborhood: str | None = None
        city: str | None = None

        neighborhood_types = {"sublocality_level_1", "sublocality", "neighborhood"}
        city_types = {"locality", "administrative_area_level_2"}

        for component in components:
            if not isinstance(component, dict):
                continue
            types = set(component.get("types") or [])
            long_text = component.get("longText")
            if not isinstance(long_text, str) or not long_text:
                continue
            if neighborhood is None and types & neighborhood_types:
                neighborhood = long_text
            if city is None and types & city_types:
                city = long_text

        return neighborhood, city

    @staticmethod
    def _map_price_level(price_level: Any) -> int | None:
        mapping = {
            "PRICE_LEVEL_INEXPENSIVE": 1,
            "PRICE_LEVEL_MODERATE": 2,
            "PRICE_LEVEL_EXPENSIVE": 3,
            "PRICE_LEVEL_VERY_EXPENSIVE": 4,
        }
        if isinstance(price_level, str):
            return mapping.get(price_level)
        return None

    @staticmethod
    def _map_details_location(location: Any) -> PlaceDetailsLocation | None:
        if not isinstance(location, dict):
            return None
        lat = location.get("latitude")
        lng = location.get("longitude")
        if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
            return None
        return PlaceDetailsLocation(latitude=lat, longitude=lng)

    async def _post_json(
        self,
        path: str,
        *,
        body: dict[str, Any],
        field_mask: str | None,
    ) -> dict[str, Any]:
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self._settings.google_maps_api_key or "",
        }
        if field_mask:
            headers["X-Goog-FieldMask"] = field_mask

        try:
            response = await self._http_client.post(
                f"{self._settings.google_places_base_url}/{path}",
                headers=headers,
                json=body,
                timeout=self._settings.google_places_timeout_seconds,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ExternalServiceError("google_places", "Timeout ao chamar o Google Places.") from exc
        except httpx.HTTPStatusError as exc:
            message = self._extract_error_message(exc.response)
            raise ExternalServiceError("google_places", f"Falha ao chamar o Google Places: {message}") from exc
        except httpx.HTTPError as exc:
            raise ExternalServiceError("google_places", "Erro de rede ao chamar o Google Places.") from exc

        return response.json() or {}

    async def _get_json(
        self,
        path: str,
        *,
        field_mask: str,
    ) -> dict[str, Any]:
        try:
            response = await self._http_client.get(
                f"{self._settings.google_places_base_url}/{path}",
                headers={
                    "X-Goog-Api-Key": self._settings.google_maps_api_key or "",
                    "X-Goog-FieldMask": field_mask,
                },
                timeout=self._settings.google_places_timeout_seconds,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ExternalServiceError("google_places", "Timeout ao chamar o Google Places.") from exc
        except httpx.HTTPStatusError as exc:
            message = self._extract_error_message(exc.response)
            raise ExternalServiceError("google_places", f"Falha ao chamar o Google Places: {message}") from exc
        except httpx.HTTPError as exc:
            raise ExternalServiceError("google_places", "Erro de rede ao chamar o Google Places.") from exc

        return response.json() or {}

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

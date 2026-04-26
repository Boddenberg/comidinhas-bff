from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RankPreference(str, Enum):
    POPULARITY = "POPULARITY"
    DISTANCE = "DISTANCE"


class NearbyRestaurantsRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    radius_meters: int = Field(default=1500, ge=1, le=50000)
    max_results: int = Field(default=10, ge=1, le=20)
    included_types: list[str] = Field(default_factory=lambda: ["restaurant"])
    excluded_types: list[str] = Field(default_factory=list)
    rank_preference: RankPreference = RankPreference.POPULARITY
    language_code: str | None = None
    region_code: str | None = None


class RestaurantLocation(BaseModel):
    latitude: float
    longitude: float


class PhotoAttribution(BaseModel):
    display_name: str | None = None
    uri: str | None = None
    photo_uri: str | None = None


class NearbyRestaurant(BaseModel):
    id: str
    display_name: str
    formatted_address: str | None = None
    location: RestaurantLocation | None = None
    rating: float | None = None
    user_rating_count: int | None = None
    price_level: str | None = None
    primary_type: str | None = None
    google_maps_uri: str | None = None
    website_uri: str | None = None
    phone_number: str | None = None
    open_now: bool | None = None
    photo_uri: str | None = None
    photo_attributions: list[PhotoAttribution] = Field(default_factory=list)
    photo_name: str | None = Field(default=None, exclude=True)


class NearbyRestaurantsResponse(BaseModel):
    places: list[NearbyRestaurant]


# ------------------------------------------------------------------ autocomplete

class LocationBias(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    radius_meters: float = Field(default=5000.0, ge=1, le=50000)


class PlaceAutocompleteRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    input: str = Field(..., min_length=1, max_length=200)
    location_bias: LocationBias | None = None
    location_restriction: LocationBias | None = None
    included_primary_types: list[str] = Field(
        default_factory=lambda: ["restaurant", "food", "cafe", "bakery", "bar"],
    )
    included_region_codes: list[str] = Field(default_factory=lambda: ["br"])
    language_code: str | None = None
    session_token: str | None = None
    include_query_predictions: bool = True
    max_results: int = Field(default=5, ge=1, le=20)


class MatchedSubstring(BaseModel):
    start_offset: int
    end_offset: int


class PredictionText(BaseModel):
    text: str
    matches: list[MatchedSubstring] = Field(default_factory=list)


class PlacePrediction(BaseModel):
    type: Literal["place"] = "place"
    place_id: str
    text: PredictionText
    main_text: PredictionText | None = None
    secondary_text: PredictionText | None = None
    types: list[str] = Field(default_factory=list)
    distance_meters: int | None = None


class QueryPrediction(BaseModel):
    type: Literal["query"] = "query"
    text: PredictionText
    main_text: PredictionText | None = None
    secondary_text: PredictionText | None = None


class PlaceAutocompleteResponse(BaseModel):
    suggestions: list[PlacePrediction | QueryPrediction] = Field(default_factory=list)


# ------------------------------------------------------------------ place details

class PlaceDetailsLocation(BaseModel):
    latitude: float
    longitude: float


class PlaceDetailsResponse(BaseModel):
    place_id: str
    display_name: str
    formatted_address: str | None = None
    location: PlaceDetailsLocation | None = None
    neighborhood: str | None = None
    city: str | None = None
    rating: float | None = None
    user_rating_count: int | None = None
    price_level: str | None = None
    price_range: int | None = Field(default=None, ge=1, le=4)
    primary_type: str | None = None
    primary_type_display_name: str | None = None
    google_maps_uri: str | None = None
    website_uri: str | None = None
    phone_number: str | None = None
    open_now: bool | None = None
    photo_uri: str | None = None
    types: list[str] = Field(default_factory=list)


# ------------------------------------------------------------------ save from Google

class SaveFromGoogleRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    place_id: str = Field(..., min_length=4, max_length=500, description="Google Place ID")
    grupo_id: str = Field(..., min_length=8, max_length=64, description="UUID do grupo")
    status: str = Field(default="quero_ir", pattern="^(quero_ir|fomos|quero_voltar|nao_curti)$")
    favorito: bool = False
    notas: str | None = Field(default=None, max_length=2000)
    adicionado_por: str | None = Field(default=None, max_length=80)

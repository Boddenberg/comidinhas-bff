from enum import Enum

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

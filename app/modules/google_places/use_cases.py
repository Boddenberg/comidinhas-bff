from app.integrations.google_places.client import GooglePlacesClient
from app.modules.google_places.schemas import (
    NearbyRestaurantsRequest,
    NearbyRestaurantsResponse,
)


class SearchNearbyRestaurantsUseCase:
    def __init__(self, client: GooglePlacesClient) -> None:
        self._client = client

    async def execute(
        self,
        request: NearbyRestaurantsRequest,
    ) -> NearbyRestaurantsResponse:
        places = await self._client.search_nearby_restaurants(request)
        return NearbyRestaurantsResponse(places=places)

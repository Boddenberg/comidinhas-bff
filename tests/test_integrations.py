import httpx
import pytest

from app.core.config import Settings
from app.integrations.google_places.client import GooglePlacesClient
from app.integrations.openai.client import OpenAIClient
from app.modules.google_places.schemas import NearbyRestaurantsRequest


@pytest.mark.anyio
async def test_openai_client_extracts_output_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/responses"
        return httpx.Response(
            status_code=200,
            json={"output_text": "Resposta sintetizada"},
        )

    settings = Settings(openai_api_key="test-key")
    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(base_url="https://api.openai.com", transport=transport) as client:
        openai_client = OpenAIClient(http_client=client, settings=settings)
        response = await openai_client.chat(
            prompt="User: oi\nAssistant:",
            system_prompt="Seja breve",
            model="gpt-4o-mini",
        )

    assert response == "Resposta sintetizada"


@pytest.mark.anyio
async def test_google_places_client_maps_places_and_photo_uri() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/places:searchNearby"):
            return httpx.Response(
                status_code=200,
                json={
                    "places": [
                        {
                            "id": "place-1",
                            "displayName": {"text": "Cantina Central"},
                            "formattedAddress": "Rua A, 123",
                            "location": {
                                "latitude": -23.55,
                                "longitude": -46.63,
                            },
                            "rating": 4.8,
                            "userRatingCount": 120,
                            "priceLevel": "PRICE_LEVEL_MODERATE",
                            "primaryType": "restaurant",
                            "googleMapsUri": "https://maps.google.com/?cid=1",
                            "photos": [
                                {
                                    "name": "places/place-1/photos/photo-1",
                                    "authorAttributions": [
                                        {
                                            "displayName": "Autor Teste",
                                            "uri": "https://example.com/autor",
                                            "photoUri": "https://example.com/avatar",
                                        }
                                    ],
                                }
                            ],
                            "regularOpeningHours": {"openNow": True},
                        }
                    ]
                },
            )

        if request.url.path.endswith("/places/place-1/photos/photo-1/media"):
            return httpx.Response(
                status_code=200,
                json={"photoUri": "https://images.example.com/place-1.jpg"},
            )

        return httpx.Response(status_code=404)

    settings = Settings(google_maps_api_key="maps-key")
    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(
        base_url="https://places.googleapis.com",
        transport=transport,
    ) as client:
        google_places_client = GooglePlacesClient(
            http_client=client,
            settings=settings,
        )
        response = await google_places_client.search_nearby_restaurants(
            NearbyRestaurantsRequest(
                latitude=-23.55,
                longitude=-46.63,
            )
        )

    assert response[0].display_name == "Cantina Central"
    assert response[0].photo_uri == "https://images.example.com/place-1.jpg"
    assert response[0].open_now is True

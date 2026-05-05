import pytest

from app.core.config import Settings
from app.modules.google_places.schemas import NearbyRestaurant
from app.modules.guias_ai.places_enricher import PlacesEnricher
from app.modules.guias_ai.schemas import ExtractedRestaurant, StatusMatching


class FakeGooglePlacesClient:
    def __init__(self) -> None:
        self.requests = []

    async def search_text_restaurants(self, request):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        if request.included_type is None and request.text_query == "Tocco Burger":
            return [
                NearbyRestaurant(
                    id="google-tocco-burger",
                    display_name="Tocco Burger",
                    formatted_address="Rua Teste, 123 - Sao Paulo",
                    primary_type="hamburger_restaurant",
                    google_maps_uri="https://maps.google.com/?cid=tocco",
                    rating=4.6,
                    user_rating_count=320,
                )
            ]
        return []


class FakeGooglePlacesClientWithPhotoTie:
    def __init__(self) -> None:
        self.requests = []

    async def search_text_restaurants(self, request):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        return [
            NearbyRestaurant(
                id="google-sem-foto",
                display_name="Grindhouse Braserito",
                formatted_address="Rua Teste, 123 - Sao Paulo",
                google_maps_uri="https://maps.google.com/?cid=sem-foto",
                rating=4.8,
                user_rating_count=500,
            ),
            NearbyRestaurant(
                id="google-com-foto",
                display_name="Grindhouse Braserito",
                formatted_address="Rua Teste, 123 - Sao Paulo",
                google_maps_uri="https://maps.google.com/?cid=com-foto",
                rating=4.7,
                user_rating_count=450,
                photo_uri="https://lh3.googleusercontent.com/grindhouse.jpg",
            ),
        ]


@pytest.mark.anyio
async def test_places_enricher_falls_back_to_unfiltered_text_search_for_burgers() -> None:
    fake_google = FakeGooglePlacesClient()
    enricher = PlacesEnricher(
        client=fake_google,  # type: ignore[arg-type]
        settings=Settings(google_maps_api_key="maps-key"),
    )

    items, calls, photos = await enricher.enriquecer_lote(
        extracted_items=[
            ExtractedRestaurant(
                ordem=0,
                nome_original="Tocco Burger",
                nome_normalizado="tocco burger",
                categoria="hamburgueria",
            )
        ],
        guide_cidade=None,
        guide_categoria="hamburguerias",
        budget=10,
    )

    assert calls > 0
    assert photos == 0
    assert any(request.included_type is None for request in fake_google.requests)
    assert items[0].status_matching == StatusMatching.ENCONTRADO_GOOGLE
    assert items[0].place_id == "google-tocco-burger"
    assert items[0].google_maps_uri == "https://maps.google.com/?cid=tocco"


@pytest.mark.anyio
async def test_places_enricher_prefers_photo_candidate_when_match_score_ties() -> None:
    fake_google = FakeGooglePlacesClientWithPhotoTie()
    enricher = PlacesEnricher(
        client=fake_google,  # type: ignore[arg-type]
        settings=Settings(google_maps_api_key="maps-key"),
    )

    items, _calls, photos = await enricher.enriquecer_lote(
        extracted_items=[
            ExtractedRestaurant(
                ordem=0,
                nome_original="Grindhouse Braserito",
                nome_normalizado="grindhouse braserito",
                cidade="Sao Paulo",
            )
        ],
        guide_cidade="Sao Paulo",
        guide_categoria=None,
        budget=10,
    )

    assert photos == 1
    assert items[0].place_id == "google-com-foto"
    assert items[0].foto_url == "https://lh3.googleusercontent.com/grindhouse.jpg"

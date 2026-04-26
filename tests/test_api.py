from fastapi.testclient import TestClient

from app.api.dependencies import get_chat_use_case, get_nearby_restaurants_use_case
from app.main import app
from app.modules.chat.schemas import ChatResponse
from app.modules.google_places.schemas import (
    NearbyRestaurant,
    NearbyRestaurantsResponse,
)


class FakeChatUseCase:
    async def execute(self, request):  # type: ignore[no-untyped-def]
        return ChatResponse(reply=f"eco: {request.message}", model="fake-model")


class FakeNearbyRestaurantsUseCase:
    async def execute(self, request):  # type: ignore[no-untyped-def]
        return NearbyRestaurantsResponse(
            places=[
                NearbyRestaurant(
                    id="place-1",
                    display_name="Restaurante Teste",
                    formatted_address="Rua das Flores, 100",
                    google_maps_uri="https://maps.google.com/?cid=teste",
                )
            ]
        )


def test_root() -> None:
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.json()["name"] == "Comidinhas BFF"


def test_healthcheck() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_hello_world() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/hello-world")

    assert response.status_code == 200
    assert response.json()["message"] == "Hello, world from Comidinhas BFF!"


def test_chat_route() -> None:
    app.dependency_overrides[get_chat_use_case] = FakeChatUseCase

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat",
            json={"message": "Oi, quero uma receita rapida"},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["reply"] == "eco: Oi, quero uma receita rapida"


def test_google_places_route() -> None:
    app.dependency_overrides[get_nearby_restaurants_use_case] = (
        FakeNearbyRestaurantsUseCase
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/google-maps/restaurants/nearby",
            json={
                "latitude": -23.55052,
                "longitude": -46.633308,
            },
        )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["places"][0]["display_name"] == "Restaurante Teste"


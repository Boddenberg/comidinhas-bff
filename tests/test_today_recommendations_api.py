from fastapi.testclient import TestClient

from app.api.dependencies import get_today_recommendations_use_case
from app.main import app
from app.modules.decisoes.schemas import TodayRecommendationItem, TodayRecommendationsResponse


class FakeTodayRecommendationsUseCase:
    async def execute(self, *, request):  # type: ignore[no-untyped-def]
        assert request.grupo_id == "grupo-123"
        assert request.perfil_id == "perfil-123"
        assert request.latitude == -23.55
        assert request.longitude == -46.63
        return TodayRecommendationsResponse(
            generated_at="2026-04-30T00:00:00+00:00",
            model="fake-model",
            total_candidates=1,
            places=[
                TodayRecommendationItem(
                    id="google-place-1",
                    google_place_id="google-place-1",
                    group_id=request.grupo_id,
                    name="Restaurante Novo",
                    category="restaurant",
                    price_range=2,
                    link="https://maps.google.com/?cid=1",
                    image_url="https://example.com/photo.jpg",
                    rating=4.8,
                    user_rating_count=320,
                    formatted_address="Rua A, 123",
                    recommendation_reason="Combina com hoje e ainda nao esta salvo.",
                )
            ],
        )


def test_today_recommendations_route_nao_processa_no_frontend() -> None:
    app.dependency_overrides[get_today_recommendations_use_case] = (
        lambda: FakeTodayRecommendationsUseCase()
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/recommendations/today",
            json={
                "grupo_id": "grupo-123",
                "perfil_id": "perfil-123",
                "latitude": -23.55,
                "longitude": -46.63,
                "limit": 3,
            },
        )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["places"][0]["name"] == "Restaurante Novo"
    assert payload["places"][0]["google_place_id"] == "google-place-1"
    assert payload["places"][0]["is_favorite"] is False

from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.modules.lugares.schemas import StatusLugar
from app.modules.restaurantes_base.repository import BaseRestaurantesRepository
from app.modules.restaurantes_base.schemas import (
    BuscarRestaurantesBaseRequest,
    SalvarRestauranteBaseRequest,
)
from app.modules.restaurantes_base.use_cases import SalvarRestauranteBaseUseCase


class FakeSupabaseClient:
    def __init__(self) -> None:
        self.inserted: dict | None = None

    async def get_grupo(self, *, grupo_id):  # type: ignore[no-untyped-def]
        return {"id": grupo_id, "membros": []}

    async def insert_lugar(self, *, payload):  # type: ignore[no-untyped-def]
        self.inserted = payload
        return {
            "id": "lugar-123",
            "criado_em": None,
            "atualizado_em": None,
            "fotos": [],
            **payload,
        }


def test_restaurantes_base_repository_busca_por_nome_sem_acento() -> None:
    repository = BaseRestaurantesRepository(
        index_path="app/data/restaurant_knowledge/sao_paulo/index.json",
    )

    response = repository.buscar(
        request=BuscarRestaurantesBaseRequest(
            query="mani jardim paulistano",
            max_resultados=5,
        )
    )

    assert response.total > 0
    assert response.items[0].restaurante.nome == "Maní"
    assert response.items[0].restaurante.markdown is None
    assert response.items[0].restaurante.fonte_chunk


def test_restaurantes_base_repository_busca_por_cozinha() -> None:
    repository = BaseRestaurantesRepository(
        index_path="app/data/restaurant_knowledge/sao_paulo/index.json",
    )

    response = repository.buscar(
        request=BuscarRestaurantesBaseRequest(
            query="japones liberdade sushi",
            max_resultados=10,
        )
    )

    assert response.total > 0
    assert any("JAPONESA" in item.restaurante.categoria for item in response.items)


def test_restaurantes_base_routes() -> None:
    with TestClient(app) as client:
        stats_response = client.get("/api/v1/restaurantes-base/stats")
        search_response = client.get(
            "/api/v1/restaurantes-base/buscar",
            params={"query": "arabe pinheiros", "max_resultados": 3},
        )

    assert stats_response.status_code == 200
    assert stats_response.json()["total_restaurantes"] == 398
    assert search_response.status_code == 200
    payload = search_response.json()
    assert payload["total"] > 0
    assert payload["items"][0]["restaurante"]["markdown"] is None


@pytest.mark.anyio
async def test_salvar_restaurante_base_preserva_origem() -> None:
    repository = BaseRestaurantesRepository(
        index_path="app/data/restaurant_knowledge/sao_paulo/index.json",
    )
    supabase = FakeSupabaseClient()
    use_case = SalvarRestauranteBaseUseCase(
        repository=repository,
        supabase_client=supabase,  # type: ignore[arg-type]
    )

    response = await use_case.execute(
        request=SalvarRestauranteBaseRequest(
            restaurante_id="mani",
            grupo_id="grupo-123",
            status=StatusLugar.QUERO_IR,
            favorito=True,
        )
    )

    assert response.nome == "Maní"
    assert response.favorito is True
    assert response.extra["source"] == "base_conhecimento"
    assert response.extra["base_restaurante_id"] == "mani"
    assert response.extra["base_fonte_chunk"]

import json

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_decidir_restaurante_use_case
from app.main import app
from app.modules.decisoes.schemas import (
    DecidirRestauranteRequest,
    DecidirRestauranteResponse,
    DecisaoRestauranteItem,
    EscopoDecisao,
)
from app.modules.decisoes.use_cases import DecidirRestauranteUseCase
from app.modules.lugares.schemas import LugarResponse, StatusLugar


def build_lugar(
    lugar_id: str,
    *,
    grupo_id: str = "grupo-123",
    nome: str,
    status: str = "quero_ir",
    favorito: bool = False,
) -> dict:
    return {
        "id": lugar_id,
        "grupo_id": grupo_id,
        "nome": nome,
        "categoria": "Restaurante",
        "bairro": "Centro",
        "cidade": "Sao Paulo",
        "faixa_preco": 2,
        "status": status,
        "favorito": favorito,
        "notas": "Boa opcao para jantar.",
        "fotos": [],
        "extra": {},
    }


class FakeOpenAIClient:
    def __init__(self, lugar_id: str = "lugar-002") -> None:
        self.lugar_id = lugar_id
        self.last_prompt = ""

    async def chat(self, *, prompt, system_prompt, model):  # type: ignore[no-untyped-def]
        self.last_prompt = prompt
        return json.dumps(
            {
                "escolha": {
                    "lugar_id": self.lugar_id,
                    "motivo": "Combina melhor com o mood informado.",
                    "pontos_fortes": ["Boa categoria", "Preco adequado"],
                    "ressalvas": [],
                    "confianca": 0.86,
                },
                "alternativas": [],
            }
        )


class FakeDecisaoSupabaseClient:
    def __init__(self) -> None:
        self.groups = {"grupo-123": {"id": "grupo-123"}}
        self.places = {
            "lugar-001": build_lugar("lugar-001", nome="Burger", status="fomos", favorito=True),
            "lugar-002": build_lugar("lugar-002", nome="Arabe Novo", status="quero_ir"),
            "lugar-003": build_lugar("lugar-003", nome="Pizza Favorita", status="quero_voltar", favorito=True),
        }
        self.last_filters: list[tuple[str, str]] = []

    async def get_grupo(self, *, grupo_id):  # type: ignore[no-untyped-def]
        return self.groups.get(grupo_id)

    async def list_lugares(
        self,
        *,
        grupo_id,
        select,
        filters,
        sort_field,
        sort_descending,
        page,
        page_size,
    ):  # type: ignore[no-untyped-def]
        self.last_filters = filters
        rows = [place for place in self.places.values() if place["grupo_id"] == grupo_id]
        for key, value in filters:
            if (key, value) == ("favorito", "eq.true"):
                rows = [place for place in rows if place["favorito"]]
            if (key, value) == ("status", "eq.quero_ir"):
                rows = [place for place in rows if place["status"] == "quero_ir"]
        return rows[:page_size], len(rows)

    async def get_guia(self, *, guia_id):  # type: ignore[no-untyped-def]
        if guia_id == "guia-123":
            return {"id": guia_id, "grupo_id": "grupo-123", "lugar_ids": ["lugar-001", "lugar-002"]}
        return None

    async def get_lugar(self, *, lugar_id, select="*"):  # type: ignore[no-untyped-def]
        return self.places.get(lugar_id)


@pytest.mark.anyio
async def test_decidir_restaurante_quero_ir_filtra_candidatos() -> None:
    fake_openai = FakeOpenAIClient(lugar_id="lugar-002")
    fake_supabase = FakeDecisaoSupabaseClient()
    use_case = DecidirRestauranteUseCase(
        openai_client=fake_openai,  # type: ignore[arg-type]
        supabase_client=fake_supabase,  # type: ignore[arg-type]
        model="fake-model",
    )

    response = await use_case.execute(
        request=DecidirRestauranteRequest(
            grupo_id="grupo-123",
            escopo=EscopoDecisao.QUERO_IR,
            criterios={"mood": "quero novidade", "orcamento_max": 2},
        )
    )

    assert fake_supabase.last_filters == [("status", "eq.quero_ir")]
    assert response.escolha.lugar.id == "lugar-002"
    assert response.total_candidatos == 1
    assert "quero novidade" in fake_openai.last_prompt


@pytest.mark.anyio
async def test_decidir_restaurante_favoritos_filtra_favoritos() -> None:
    fake_supabase = FakeDecisaoSupabaseClient()
    use_case = DecidirRestauranteUseCase(
        openai_client=FakeOpenAIClient(lugar_id="lugar-003"),  # type: ignore[arg-type]
        supabase_client=fake_supabase,  # type: ignore[arg-type]
        model="fake-model",
    )

    response = await use_case.execute(
        request=DecidirRestauranteRequest(
            grupo_id="grupo-123",
            escopo=EscopoDecisao.FAVORITOS,
        )
    )

    assert fake_supabase.last_filters == [("favorito", "eq.true")]
    assert response.escolha.lugar.id == "lugar-003"
    assert response.total_candidatos == 2


@pytest.mark.anyio
async def test_decidir_restaurante_guia_usa_lugares_do_guia() -> None:
    use_case = DecidirRestauranteUseCase(
        openai_client=FakeOpenAIClient(lugar_id="lugar-001"),  # type: ignore[arg-type]
        supabase_client=FakeDecisaoSupabaseClient(),  # type: ignore[arg-type]
        model="fake-model",
    )

    response = await use_case.execute(
        request=DecidirRestauranteRequest(
            grupo_id="grupo-123",
            escopo=EscopoDecisao.GUIA,
            guia_id="guia-123",
        )
    )

    assert response.guia_id == "guia-123"
    assert response.escolha.lugar.id == "lugar-001"
    assert response.total_candidatos == 2


class FakeDecidirRestauranteUseCase:
    async def execute(self, *, request):  # type: ignore[no-untyped-def]
        assert request.grupo_id == "grupo-123"
        return DecidirRestauranteResponse(
            grupo_id="grupo-123",
            escopo=EscopoDecisao.QUERO_IR,
            escolha=DecisaoRestauranteItem(
                lugar=LugarResponse(
                    id="lugar-002",
                    grupo_id="grupo-123",
                    nome="Arabe Novo",
                    status=StatusLugar.QUERO_IR,
                ),
                motivo="Combina com o mood.",
                confianca=0.8,
            ),
            total_candidatos=1,
            criterios_usados={"mood": "novidade"},
            modelo="fake-model",
        )


def test_decidir_restaurante_route_nao_exige_bearer_token() -> None:
    app.dependency_overrides[get_decidir_restaurante_use_case] = lambda: FakeDecidirRestauranteUseCase()

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/ia/decidir-restaurante",
            json={
                "grupo_id": "grupo-123",
                "escopo": "quero_ir",
                "criterios": {"mood": "novidade"},
            },
        )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["escolha"]["lugar"]["id"] == "lugar-002"

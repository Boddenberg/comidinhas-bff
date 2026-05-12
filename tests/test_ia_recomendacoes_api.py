import json

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_recomendar_restaurantes_use_case
from app.main import app
from app.modules.decisoes.recomendacoes import RecomendarRestaurantesUseCase
from app.modules.decisoes.schemas import (
    EstadoRecomendacao,
    InterpretacaoRecomendacao,
    OrigemCandidato,
    RecomendacaoRestauranteItem,
    RecomendarRestaurantesRequest,
    RecomendarRestaurantesResponse,
)
from app.modules.restaurantes_base.schemas import (
    BuscarRestaurantesBaseResponse,
    RestauranteBase,
    RestauranteBaseResultado,
)


def build_lugar(lugar_id: str, *, nome: str, status: str = "quero_ir", favorito: bool = False) -> dict:
    return {
        "id": lugar_id,
        "grupo_id": "grupo-123",
        "nome": nome,
        "categoria": "Arabe",
        "bairro": "Pinheiros",
        "cidade": "Sao Paulo",
        "faixa_preco": 2,
        "status": status,
        "favorito": favorito,
        "notas": "Boa opcao para jantar.",
        "fotos": [],
        "extra": {},
    }


class FakeOpenAIJsonClient:
    def __init__(self, *, precisa_localizacao: bool = False) -> None:
        self.precisa_localizacao = precisa_localizacao
        self.prompts: list[dict] = []

    async def chat_json(self, *, prompt, system_prompt, model, schema_name, schema):  # type: ignore[no-untyped-def]
        payload = json.loads(prompt)
        self.prompts.append(payload)
        if schema_name == "interpretacao_recomendacao_restaurante":
            return {
                "intencao": "recomendacao_restaurante",
                "cozinhas": ["arabe"],
                "termos_busca": ["restaurante arabe"],
                "momento": "hoje",
                "localizacao_texto": None,
                "estrategia": "hibrida",
                "precisa_localizacao": self.precisa_localizacao,
                "preferencia_novidade": "auto",
                "preferencias": [],
                "restricoes": [],
                "orcamento_max": None,
                "quantidade_pessoas": None,
                "pergunta_refinamento": None,
                "confianca": 0.92,
            }

        candidatos = payload["candidatos"]
        return {
            "resumo": "Encontrei opcoes arabes para hoje.",
            "pergunta_refinamento": None,
            "opcoes": [
                {
                    "candidato_id": item["candidato_id"],
                    "motivo": "Combina com comida arabe hoje.",
                    "pontos_fortes": ["Combina com o pedido"],
                    "ressalvas": [],
                    "confianca": 0.83,
                }
                for item in candidatos[:2]
            ],
        }


class FakeRestaurantesBase:
    def __init__(self) -> None:
        self.requests = []

    def buscar(self, *, request):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        return BuscarRestaurantesBaseResponse(
            query=request.query,
            total=1,
            versao="fake",
            cidade="Sao Paulo",
            items=[
                RestauranteBaseResultado(
                    score=8.5,
                    trechos=["Restaurante arabe da base propria."],
                    restaurante=RestauranteBase(
                        id="arabe-novo",
                        nome="Arabe Novo",
                        categoria_id="08-arabe-libanesa-oriente-medio",
                        categoria="ARABE / LIBANESA / ORIENTE MEDIO",
                        tipo="Arabe",
                        endereco="Rua B, 200 - Pinheiros",
                        bairro="Pinheiros",
                        cidade="Sao Paulo",
                        descricao="Restaurante arabe da base propria.",
                        fonte_chunk="chunks/by_restaurant/999-arabe-novo.md",
                    ),
                )
            ],
        )


class FakeSupabaseClient:
    def __init__(self, places: list[dict] | None = None) -> None:
        self.groups = {"grupo-123": {"id": "grupo-123"}}
        self.places = places if places is not None else []

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
        rows = [place for place in self.places if place["grupo_id"] == grupo_id]
        return rows[:page_size], len(rows)


@pytest.mark.anyio
async def test_recomendar_restaurantes_mistura_supabase_e_base_conhecimento() -> None:
    fake_openai = FakeOpenAIJsonClient()
    fake_base = FakeRestaurantesBase()
    use_case = RecomendarRestaurantesUseCase(
        openai_client=fake_openai,  # type: ignore[arg-type]
        restaurantes_base=fake_base,  # type: ignore[arg-type]
        supabase_client=FakeSupabaseClient(
            places=[
                build_lugar(
                    "lugar-001",
                    nome="Casa Arabe Salva",
                    status="quero_voltar",
                    favorito=True,
                )
            ]
        ),  # type: ignore[arg-type]
        model="fake-model",
    )

    response = await use_case.execute(
        request=RecomendarRestaurantesRequest(
            grupo_id="grupo-123",
            mensagem="estou com vontade de comer arabe hoje",
            localizacao={
                "latitude": -23.55,
                "longitude": -46.63,
                "cidade": "Sao Paulo",
            },
            max_resultados=2,
        )
    )

    assert response.estado == EstadoRecomendacao.OPCOES
    assert response.resumo == "Encontrei opcoes arabes para hoje."
    assert len(response.opcoes) == 2
    assert {item.restaurante.origem for item in response.opcoes} == {
        OrigemCandidato.COMIDINHAS,
        OrigemCandidato.BASE_CONHECIMENTO,
    }
    assert fake_base.requests
    assert "arabe" in fake_base.requests[0].query
    base_option = next(
        item
        for item in response.opcoes
        if item.restaurante.origem == OrigemCandidato.BASE_CONHECIMENTO
    )
    assert base_option.restaurante.categoria == "Arabe"
    assert base_option.restaurante.base_restaurante_id == "arabe-novo"


@pytest.mark.anyio
async def test_recomendar_restaurantes_sem_base_e_sem_candidatos_pede_refinamento() -> None:
    fake_base = FakeRestaurantesBase()
    use_case = RecomendarRestaurantesUseCase(
        openai_client=FakeOpenAIJsonClient(precisa_localizacao=True),  # type: ignore[arg-type]
        restaurantes_base=fake_base,  # type: ignore[arg-type]
        supabase_client=FakeSupabaseClient(),  # type: ignore[arg-type]
        model="fake-model",
    )

    response = await use_case.execute(
        request=RecomendarRestaurantesRequest(
            grupo_id="grupo-123",
            mensagem="estou com vontade de comer arabe hoje",
            permitir_base_conhecimento=False,
        )
    )

    assert response.estado == EstadoRecomendacao.PRECISA_REFINAR
    assert response.pergunta_refinamento
    assert fake_base.requests == []


class FakeRecomendarRestaurantesUseCase:
    async def execute(self, *, request):  # type: ignore[no-untyped-def]
        assert request.grupo_id == "grupo-123"
        return RecomendarRestaurantesResponse(
            grupo_id="grupo-123",
            estado=EstadoRecomendacao.OPCOES,
            mensagem=request.mensagem,
            interpretacao=InterpretacaoRecomendacao(cozinhas=["arabe"]),
            opcoes=[
                RecomendacaoRestauranteItem(
                    restaurante={
                        "candidato_id": "base:arabe-novo",
                        "origem": "base_conhecimento",
                        "base_restaurante_id": "arabe-novo",
                        "nome": "Arabe Novo",
                        "novo_no_app": True,
                    },
                    motivo="Combina com o pedido.",
                    confianca=0.8,
                )
            ],
            total_candidatos=1,
            fontes_usadas=[OrigemCandidato.BASE_CONHECIMENTO],
            modelo="fake-model",
        )


def test_recomendar_restaurantes_route_nao_exige_bearer_token() -> None:
    app.dependency_overrides[get_recomendar_restaurantes_use_case] = (
        lambda: FakeRecomendarRestaurantesUseCase()
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/ia/recomendar-restaurantes",
            json={
                "grupo_id": "grupo-123",
                "mensagem": "quero comida arabe hoje",
                "localizacao": {"cidade": "Sao Paulo"},
            },
        )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["estado"] == "opcoes"
    assert response.json()["opcoes"][0]["restaurante"]["origem"] == "base_conhecimento"

"""Garante que o `RecomendarRestaurantesUseCase` exclui restaurantes
sugeridos recentemente, persiste no historico e enriquece o prompt
de ranking com sinais de personalizacao.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.decisoes.recomendacoes import RecomendarRestaurantesUseCase
from app.modules.decisoes.schemas import (
    EstadoRecomendacao,
    OrigemCandidato,
    RecomendarRestaurantesRequest,
)
from app.modules.google_places.schemas import NearbyRestaurant


def _historico_row(
    *,
    nome: str,
    google_place_id: str | None = None,
    lugar_id: str | None = None,
    horas_atras: float = 2,
) -> dict:
    return {
        "lugar_id": lugar_id,
        "google_place_id": google_place_id,
        "nome": nome,
        "fonte": "recomendar_restaurantes",
        "posicao": 1,
        "criterios": {"cozinhas": ["italiana"], "mood": "romantico"},
        "motivo": "previa",
        "criado_em": (datetime.now(timezone.utc) - timedelta(hours=horas_atras)).isoformat(),
    }


def _build_lugar(lugar_id: str, *, nome: str) -> dict:
    return {
        "id": lugar_id,
        "grupo_id": "grupo-123",
        "nome": nome,
        "categoria": "Italiano",
        "bairro": "Pinheiros",
        "cidade": "Sao Paulo",
        "faixa_preco": 2,
        "status": "quero_ir",
        "favorito": False,
        "notas": "",
        "fotos": [],
        "extra": {},
    }


class _FakeOpenAIRanking:
    def __init__(self) -> None:
        self.prompts: list[dict] = []

    async def chat_json(self, *, prompt, system_prompt, model, schema_name, schema):  # type: ignore[no-untyped-def]
        payload = json.loads(prompt)
        self.prompts.append({"schema": schema_name, "payload": payload})
        if schema_name == "interpretacao_recomendacao_restaurante":
            return {
                "intencao": "recomendacao_restaurante",
                "cozinhas": ["italiana"],
                "termos_busca": ["italiano"],
                "momento": "hoje",
                "localizacao_texto": None,
                "estrategia": "interna",
                "precisa_localizacao": False,
                "preferencia_novidade": "auto",
                "preferencias": [],
                "restricoes": [],
                "orcamento_max": None,
                "quantidade_pessoas": None,
                "pergunta_refinamento": None,
                "confianca": 0.9,
            }
        candidatos = payload["candidatos"]
        return {
            "resumo": "Separei algumas opcoes que sairam do padrao da semana.",
            "pergunta_refinamento": None,
            "opcoes": [
                {
                    "candidato_id": c["candidato_id"],
                    "motivo": "Esta semana voces foram em mais italianos, hoje vamos por aqui que tem ambiente leve.",
                    "pontos_fortes": ["massa fresca", "vinho da casa"],
                    "ressalvas": [],
                    "confianca": 0.83,
                }
                for c in candidatos[:2]
            ],
        }


class _FakeGoogleRecomendacoes:
    def __init__(self, places: list[NearbyRestaurant] | None = None) -> None:
        self.places = places or []
        self.requests: list = []

    async def search_text_restaurants(self, request):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        return self.places


class _FakeSupabaseRec:
    def __init__(self, *, places: list[dict], historico: list[dict] | None = None) -> None:
        self._places = places
        self._historico = historico or []
        self.persisted: list[dict] = []

    async def get_grupo(self, *, grupo_id):  # type: ignore[no-untyped-def]
        return {"id": grupo_id}

    async def list_lugares(self, **kwargs):  # type: ignore[no-untyped-def]
        rows = [p for p in self._places if p["grupo_id"] == kwargs["grupo_id"]]
        return rows[: kwargs["page_size"]], len(rows)

    async def list_sugestoes_ia_recentes(self, **_kwargs):  # type: ignore[no-untyped-def]
        return self._historico

    async def insert_sugestoes_ia(self, *, rows):  # type: ignore[no-untyped-def]
        self.persisted.extend(rows)
        return rows


@pytest.mark.anyio
async def test_recomendar_exclui_lugar_sugerido_no_dia() -> None:
    fake_supabase = _FakeSupabaseRec(
        places=[
            _build_lugar("L1", nome="Italiano A"),
            _build_lugar("L2", nome="Italiano B"),
            _build_lugar("L3", nome="Italiano C"),
        ],
        historico=[_historico_row(nome="Italiano A", lugar_id="L1", horas_atras=4)],
    )
    fake_openai = _FakeOpenAIRanking()
    use_case = RecomendarRestaurantesUseCase(
        openai_client=fake_openai,  # type: ignore[arg-type]
        google_client=_FakeGoogleRecomendacoes(),  # type: ignore[arg-type]
        supabase_client=fake_supabase,  # type: ignore[arg-type]
        model="fake",
    )

    response = await use_case.execute(
        request=RecomendarRestaurantesRequest(
            grupo_id="grupo-123",
            mensagem="quero italiano hoje",
            permitir_google=False,
            max_resultados=2,
        )
    )

    assert response.estado == EstadoRecomendacao.OPCOES
    candidato_ids = {item.restaurante.lugar_id for item in response.opcoes}
    assert "L1" not in candidato_ids
    # Confirma que o prompt de ranking recebeu o historico
    ranking_prompt = next(
        p for p in fake_openai.prompts if p["schema"] == "ranking_recomendacao_restaurantes"
    )
    assert "Italiano A" in ranking_prompt["payload"]["historico"]["ultimas"]
    assert "italiana" in ranking_prompt["payload"]["historico"]["cozinhas_frequentes"]


@pytest.mark.anyio
async def test_recomendar_persiste_opcoes_no_historico() -> None:
    fake_supabase = _FakeSupabaseRec(
        places=[
            _build_lugar("L1", nome="Italiano A"),
            _build_lugar("L2", nome="Italiano B"),
        ]
    )
    use_case = RecomendarRestaurantesUseCase(
        openai_client=_FakeOpenAIRanking(),  # type: ignore[arg-type]
        google_client=_FakeGoogleRecomendacoes(),  # type: ignore[arg-type]
        supabase_client=fake_supabase,  # type: ignore[arg-type]
        model="fake",
    )

    await use_case.execute(
        request=RecomendarRestaurantesRequest(
            grupo_id="grupo-123",
            perfil_id="perfil-1",
            mensagem="quero italiano hoje",
            permitir_google=False,
            max_resultados=2,
        )
    )

    assert len(fake_supabase.persisted) == 2
    fontes = {row["fonte"] for row in fake_supabase.persisted}
    assert fontes == {"recomendar_restaurantes"}
    perfis = {row["perfil_id"] for row in fake_supabase.persisted}
    assert perfis == {"perfil-1"}
    origens = {row["origem"] for row in fake_supabase.persisted}
    assert origens == {OrigemCandidato.COMIDINHAS.value}

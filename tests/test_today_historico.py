"""Garante que o `TodayRecommendationsUseCase` exclui restaurantes
sugeridos recentemente e persiste a sugestao no historico.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.decisoes.schemas import TodayRecommendationsRequest
from app.modules.decisoes.today_recommendations import TodayRecommendationsUseCase
from app.modules.google_places.schemas import NearbyRestaurant


def _historico_row(*, nome: str, google_place_id: str, horas_atras: float = 2) -> dict:
    return {
        "lugar_id": None,
        "google_place_id": google_place_id,
        "nome": nome,
        "fonte": "today_recommendations",
        "posicao": 1,
        "criterios": {},
        "motivo": "antiga sugestao",
        "criado_em": (datetime.now(timezone.utc) - timedelta(hours=horas_atras)).isoformat(),
    }


def _place(place_id: str, *, nome: str, rating: float = 4.6, reviews: int = 200) -> NearbyRestaurant:
    return NearbyRestaurant(
        id=place_id,
        display_name=nome,
        formatted_address="Rua X, 1",
        rating=rating,
        user_rating_count=reviews,
        price_level="PRICE_LEVEL_MODERATE",
        primary_type="restaurant",
        primary_type_display_name="Restaurante",
        google_maps_uri=f"https://maps.google.com/?cid={place_id}",
        open_now=True,
        photo_uri="https://example.com/photo.jpg",
    )


class _FakeGoogle:
    def __init__(self, places: list[NearbyRestaurant]) -> None:
        self.places = places

    async def search_nearby_restaurants(self, _request):  # type: ignore[no-untyped-def]
        return self.places


class _FakeOpenAIToday:
    def __init__(self) -> None:
        self.last_prompt = ""

    async def chat_json(self, *, prompt, system_prompt, model, schema_name, schema):  # type: ignore[no-untyped-def]
        self.last_prompt = prompt
        payload = json.loads(prompt)
        return {
            "places": [
                {
                    "candidato_id": c["candidato_id"],
                    "reason": "Hoje pede algo leve, e este lugar combina com voces depois de uma semana corrida.",
                }
                for c in payload["candidatos"][: payload["max_resultados"]]
            ]
        }


class _FakeSupabaseToday:
    def __init__(self, *, historico: list[dict] | None = None) -> None:
        self.persisted: list[dict] = []
        self._historico = historico or []

    async def get_grupo(self, *, grupo_id):  # type: ignore[no-untyped-def]
        return {"id": grupo_id}

    async def list_lugares(self, **_kwargs):  # type: ignore[no-untyped-def]
        return [], 0

    async def list_sugestoes_ia_recentes(self, **_kwargs):  # type: ignore[no-untyped-def]
        return self._historico

    async def insert_sugestoes_ia(self, *, rows):  # type: ignore[no-untyped-def]
        self.persisted.extend(rows)
        return rows


@pytest.mark.anyio
async def test_today_remove_lugar_repetido_no_dia() -> None:
    fake_google = _FakeGoogle(
        [
            _place("g-1", nome="Lugar Antigo"),
            _place("g-2", nome="Lugar Novo"),
        ]
    )
    fake_supabase = _FakeSupabaseToday(
        historico=[_historico_row(nome="Lugar Antigo", google_place_id="g-1", horas_atras=3)]
    )
    fake_openai = _FakeOpenAIToday()
    use_case = TodayRecommendationsUseCase(
        openai_client=fake_openai,  # type: ignore[arg-type]
        google_client=fake_google,  # type: ignore[arg-type]
        supabase_client=fake_supabase,  # type: ignore[arg-type]
        model="fake",
    )

    response = await use_case.execute(
        request=TodayRecommendationsRequest(
            grupo_id="grupo-123",
            latitude=-23.55,
            longitude=-46.63,
            limit=1,
            mood="leve",
        )
    )

    assert len(response.places) == 1
    assert response.places[0].google_place_id == "g-2"
    prompt = json.loads(fake_openai.last_prompt)
    candidatos_ids = {c["candidato_id"] for c in prompt["candidatos"]}
    assert "google:g-1" not in candidatos_ids


@pytest.mark.anyio
async def test_today_persiste_no_historico_apos_recomendar() -> None:
    fake_google = _FakeGoogle([_place("g-1", nome="Lugar Novo")])
    fake_supabase = _FakeSupabaseToday()
    use_case = TodayRecommendationsUseCase(
        openai_client=_FakeOpenAIToday(),  # type: ignore[arg-type]
        google_client=fake_google,  # type: ignore[arg-type]
        supabase_client=fake_supabase,  # type: ignore[arg-type]
        model="fake",
    )

    await use_case.execute(
        request=TodayRecommendationsRequest(
            grupo_id="grupo-123",
            perfil_id="perfil-1",
            latitude=-23.55,
            longitude=-46.63,
            limit=1,
            mood="leve",
            weather="ensolarado",
        )
    )

    assert len(fake_supabase.persisted) == 1
    row = fake_supabase.persisted[0]
    assert row["google_place_id"] == "g-1"
    assert row["fonte"] == "today_recommendations"
    assert row["origem"] == "google"
    assert row["criterios"]["mood"] == "leve"
    assert row["criterios"]["weather"] == "ensolarado"

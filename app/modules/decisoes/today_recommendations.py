from __future__ import annotations

import json
import logging
import math
import unicodedata
from datetime import datetime, timezone
from typing import Any

from app.core.errors import NotFoundError
from app.integrations.google_places.client import GooglePlacesClient
from app.integrations.openai.client import OpenAIClient
from app.integrations.supabase.client import SupabaseClient
from app.modules.decisoes import historico
from app.modules.decisoes.schemas import (
    TodayRecommendationItem,
    TodayRecommendationsRequest,
    TodayRecommendationsResponse,
)
from app.modules.google_places.place_types import friendly_place_type
from app.modules.google_places.schemas import NearbyRestaurant, NearbyRestaurantsRequest, RankPreference
from app.modules.lugares.schemas import LugarResponse
from app.modules.lugares.use_cases import ManageLugaresUseCase

logger = logging.getLogger(__name__)

_MIN_RATING = 4.2
_MIN_REVIEWS = 40
_PRICE_LEVEL_MAP = {
    "PRICE_LEVEL_INEXPENSIVE": 1,
    "PRICE_LEVEL_MODERATE": 2,
    "PRICE_LEVEL_EXPENSIVE": 3,
    "PRICE_LEVEL_VERY_EXPENSIVE": 4,
}


class TodayRecommendationsUseCase:
    SYSTEM_PROMPT = (
        "Voce e um concierge gastronomico do app Comidinhas. "
        "Escolha restaurantes novos para o perfil entre candidatos do Google Places "
        "e escreva uma justificativa pessoal, calorosa e especifica para cada um, "
        "como se voce conhecesse o gosto deste grupo. "
        "Use somente candidato_id recebido. Priorize avaliacao, volume de reviews, "
        "lugar aberto e boa combinacao com o clima/humor. "
        "Evite frases genericas como 'boa avaliacao' - destaque um detalhe "
        "concreto do lugar e conecte com o momento ou com o historico recente."
    )
    FONTE = "today_recommendations"
    RANKING_SCHEMA: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "places": {
                "type": "array",
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "candidato_id": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["candidato_id", "reason"],
                },
            }
        },
        "required": ["places"],
    }

    def __init__(
        self,
        *,
        openai_client: OpenAIClient,
        google_client: GooglePlacesClient,
        supabase_client: SupabaseClient,
        model: str,
    ) -> None:
        self._openai = openai_client
        self._google = google_client
        self._supabase = supabase_client
        self._model = model

    async def execute(self, *, request: TodayRecommendationsRequest) -> TodayRecommendationsResponse:
        grupo = await self._supabase.get_grupo(grupo_id=request.grupo_id)
        if grupo is None:
            raise NotFoundError("Grupo nao encontrado.")

        saved_places = await self._load_saved_places(request.grupo_id)
        contexto = await historico.carregar_contexto(
            supabase_client=self._supabase, grupo_id=request.grupo_id
        )
        contexto.lugares_signal = [
            {
                "categoria": p.categoria,
                "bairro": p.bairro,
                "status": p.status.value,
                "favorito": p.favorito,
            }
            for p in saved_places
        ]
        preferencias = contexto.preferencias_inferidas()
        nearby = await self._google.search_nearby_restaurants(
            NearbyRestaurantsRequest(
                latitude=request.latitude,
                longitude=request.longitude,
                radius_meters=request.radius_meters,
                max_results=20,
                included_types=["restaurant"],
                rank_preference=RankPreference.POPULARITY,
            )
        )

        fresh = self._exclude_saved(nearby, saved_places)
        fresh = self._exclude_history(fresh, contexto)
        if preferencias.google_recusados_ids:
            fresh = [
                place for place in fresh
                if place.id not in preferencias.google_recusados_ids
            ] or fresh
        candidates = self._quality_candidates(fresh)
        if len(candidates) < request.limit:
            candidates = self._fill_with_available(candidates=candidates, fresh=fresh, limit=request.limit)

        ranked = await self._rank_with_ai(
            request=request,
            candidates=candidates,
            contexto=contexto,
            preferencias=preferencias,
        )
        by_candidate_id = {f"google:{place.id}": place for place in candidates}
        places = [
            self._to_response_item(
                place=by_candidate_id[item["candidato_id"]],
                grupo_id=request.grupo_id,
                reason=item["reason"],
            )
            for item in ranked
            if item["candidato_id"] in by_candidate_id
        ][: request.limit]

        persisted = await historico.registrar_sugestoes(
            supabase_client=self._supabase,
            grupo_id=request.grupo_id,
            perfil_id=request.perfil_id,
            fonte=self.FONTE,
            modelo=self._model,
            criterios={
                "mood": request.mood,
                "weather": request.weather,
                "latitude": request.latitude,
                "longitude": request.longitude,
            },
            sugestoes=[
                {
                    "nome": place.name,
                    "google_place_id": place.google_place_id,
                    "origem": "google",
                    "motivo": place.recommendation_reason,
                    "categoria": place.category,
                    "bairro": place.neighborhood,
                }
                for place in places
            ],
        )
        self._hidratar_ids(places, persistidas=persisted)

        return TodayRecommendationsResponse(
            generated_at=datetime.now(timezone.utc).isoformat(),
            places=places,
            total_candidates=len(candidates),
            model=self._model,
        )

    async def _load_saved_places(self, grupo_id: str) -> list[LugarResponse]:
        rows, _ = await self._supabase.list_lugares(
            grupo_id=grupo_id,
            select=ManageLugaresUseCase.SELECT,
            filters=[],
            sort_field="criado_em",
            sort_descending=True,
            page=1,
            page_size=100,
        )
        return [ManageLugaresUseCase._mapear(row) for row in rows if isinstance(row, dict)]

    @staticmethod
    def _hidratar_ids(
        items: list[TodayRecommendationItem],
        *,
        persistidas: list[dict],
    ) -> None:
        if not persistidas:
            return
        por_google: dict[str, str] = {}
        for row in persistidas:
            google_place_id = row.get("google_place_id")
            sugestao_id = row.get("id")
            if isinstance(google_place_id, str) and isinstance(sugestao_id, str):
                por_google.setdefault(google_place_id, sugestao_id)
        for item in items:
            sugestao_id = por_google.get(item.google_place_id)
            if sugestao_id:
                item.sugestao_id = sugestao_id

    async def _rank_with_ai(
        self,
        *,
        request: TodayRecommendationsRequest,
        candidates: list[NearbyRestaurant],
        contexto: historico.HistoricoContexto,
        preferencias: historico.PreferenciasInferidas,
    ) -> list[dict[str, str]]:
        if not candidates:
            return []

        personalizacao = contexto.resumo_personalizacao()
        nomes_recentes = [sug.nome for sug in contexto.sugestoes if sug.nome][:8]

        prompt = json.dumps(
            {
                "max_resultados": request.limit,
                "mood": request.mood,
                "weather": request.weather,
                "regras": [
                    "Escolha exatamente max_resultados quando houver candidatos suficientes.",
                    "Nao escolha candidatos duplicados.",
                    "Todos os candidatos ja foram filtrados para nao existirem no perfil/grupo nem aparecerem no historico recente.",
                    "Para cada escolhido, escreva 'reason' com 1 a 2 frases pessoais, em portugues, com um detalhe concreto do lugar e uma conexao com o mood, clima, ou com a variacao em relacao ao historico (ex: 'Esta semana voces foram em japones, hoje quebro o padrao com este italiano de massa fresca').",
                    "Evite chavoes como 'boa avaliacao', 'bem avaliado', 'otima opcao'. Prefira detalhes especificos.",
                    "Prefira rating alto, muitos reviews, foto, link do Maps e aberto agora.",
                ],
                "historico": {
                    "ultimas": nomes_recentes,
                    "cozinhas_frequentes": personalizacao.get("cozinhas_frequentes", []),
                    "moods_frequentes": personalizacao.get("moods_frequentes", []),
                    "total_sugestoes_30d": personalizacao.get("total_sugestoes_30d", 0),
                },
                "preferencias_aprendidas": preferencias.to_prompt(),
                "candidatos": [self._candidate_prompt(place) for place in candidates[:15]],
            },
            ensure_ascii=False,
        )

        raw = await self._openai.chat_json(
            prompt=prompt,
            system_prompt=self.SYSTEM_PROMPT,
            model=self._model,
            schema_name="today_restaurant_recommendations",
            schema=self.RANKING_SCHEMA,
        )
        selected = raw.get("places")
        if not isinstance(selected, list):
            return self._fallback_rank(candidates=candidates, limit=request.limit)

        result: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in selected:
            if not isinstance(item, dict):
                continue
            candidato_id = item.get("candidato_id")
            if not isinstance(candidato_id, str) or candidato_id in seen:
                continue
            seen.add(candidato_id)
            reason = item.get("reason")
            result.append(
                {
                    "candidato_id": candidato_id,
                    "reason": reason if isinstance(reason, str) and reason.strip() else _default_reason(),
                }
            )
        return result or self._fallback_rank(candidates=candidates, limit=request.limit)

    @staticmethod
    def _exclude_saved(
        candidates: list[NearbyRestaurant],
        saved_places: list[LugarResponse],
    ) -> list[NearbyRestaurant]:
        saved_google_ids = {
            str(place.extra.get("google_place_id"))
            for place in saved_places
            if isinstance(place.extra, dict) and place.extra.get("google_place_id")
        }
        saved_links = {place.link for place in saved_places if place.link}
        saved_names = {_normalize(place.nome) for place in saved_places if place.nome}

        return [
            place
            for place in candidates
            if place.id not in saved_google_ids
            and place.google_maps_uri not in saved_links
            and _normalize(place.display_name) not in saved_names
        ]

    @staticmethod
    def _exclude_history(
        candidates: list[NearbyRestaurant],
        contexto: historico.HistoricoContexto,
    ) -> list[NearbyRestaurant]:
        evitar_dia = contexto.google_evitar_dia()
        evitar_semana = contexto.google_evitar_semana()
        nomes_recentes = {
            _normalize(sug.nome)
            for sug in contexto.sugestoes
            if sug.nome and sug.criado_em is not None
            and (contexto.agora - sug.criado_em).total_seconds() < historico.WINDOW_DAY_HOURS * 3600
        }

        # Janela de 24h: sempre exclui (ids E nomes).
        passo_dia = [
            place
            for place in candidates
            if place.id not in evitar_dia
            and _normalize(place.display_name) not in nomes_recentes
        ]
        # Janela de 7d: exclui se ainda sobrar gente para escolher.
        if evitar_semana:
            passo_semana = [place for place in passo_dia if place.id not in evitar_semana]
            if passo_semana:
                return passo_semana
        return passo_dia

    @staticmethod
    def _quality_candidates(candidates: list[NearbyRestaurant]) -> list[NearbyRestaurant]:
        return [
            place
            for place in candidates
            if (place.rating or 0) >= _MIN_RATING
            and (place.user_rating_count or 0) >= _MIN_REVIEWS
            and place.open_now is not False
        ]

    @staticmethod
    def _fill_with_available(
        *,
        candidates: list[NearbyRestaurant],
        fresh: list[NearbyRestaurant],
        limit: int,
    ) -> list[NearbyRestaurant]:
        selected_ids = {place.id for place in candidates}
        relaxed = [place for place in fresh if place.id not in selected_ids]
        return [*candidates, *sorted(relaxed, key=_score_place, reverse=True)][:limit]

    @staticmethod
    def _fallback_rank(
        *,
        candidates: list[NearbyRestaurant],
        limit: int,
    ) -> list[dict[str, str]]:
        return [
            {"candidato_id": f"google:{place.id}", "reason": _default_reason()}
            for place in sorted(candidates, key=_score_place, reverse=True)[:limit]
        ]

    @staticmethod
    def _candidate_prompt(place: NearbyRestaurant) -> dict[str, Any]:
        return {
            "candidato_id": f"google:{place.id}",
            "nome": place.display_name,
            "categoria": friendly_place_type(
                place.primary_type,
                place.primary_type_display_name,
            ),
            "endereco": place.formatted_address,
            "rating": place.rating,
            "user_rating_count": place.user_rating_count,
            "price_level": place.price_level,
            "open_now": place.open_now,
            "has_photo": bool(place.photo_uri),
            "has_maps_link": bool(place.google_maps_uri),
        }

    @staticmethod
    def _to_response_item(
        *,
        place: NearbyRestaurant,
        grupo_id: str,
        reason: str,
    ) -> TodayRecommendationItem:
        return TodayRecommendationItem(
            id=place.id,
            google_place_id=place.id,
            group_id=grupo_id,
            name=place.display_name,
            category=friendly_place_type(
                place.primary_type,
                place.primary_type_display_name,
            ),
            price_range=_PRICE_LEVEL_MAP.get(place.price_level or ""),
            link=place.google_maps_uri or place.website_uri,
            notes=reason,
            image_url=place.photo_uri,
            rating=place.rating,
            user_rating_count=place.user_rating_count,
            photos=[photo.model_dump(mode="json") for photo in place.photos],
            formatted_address=place.formatted_address,
            recommendation_reason=reason,
        )


def _score_place(place: NearbyRestaurant) -> float:
    rating = place.rating or 0
    reviews = place.user_rating_count or 0
    return (rating * 2) + (min(math.log10(reviews + 1), 4) / 4) + (0.15 if place.open_now else 0)


def _normalize(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    without_accents = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return " ".join(without_accents.lower().split())


def _default_reason() -> str:
    return (
        "Escolhi este pensando em algo novo pra hoje - tem boa reputacao "
        "no bairro e ainda nao apareceu por aqui."
    )

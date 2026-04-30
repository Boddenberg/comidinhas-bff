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
from app.modules.decisoes.schemas import (
    TodayRecommendationItem,
    TodayRecommendationsRequest,
    TodayRecommendationsResponse,
)
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
        "Escolha restaurantes novos para o perfil entre candidatos do Google Places. "
        "Use somente candidato_id recebido. Priorize avaliacao, volume de reviews, lugar aberto "
        "e boa combinacao com o clima/humor."
    )
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
        candidates = self._quality_candidates(fresh)
        if len(candidates) < request.limit:
            candidates = self._fill_with_available(candidates=candidates, fresh=fresh, limit=request.limit)

        ranked = await self._rank_with_ai(request=request, candidates=candidates)
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

    async def _rank_with_ai(
        self,
        *,
        request: TodayRecommendationsRequest,
        candidates: list[NearbyRestaurant],
    ) -> list[dict[str, str]]:
        if not candidates:
            return []

        prompt = json.dumps(
            {
                "max_resultados": request.limit,
                "mood": request.mood,
                "weather": request.weather,
                "regras": [
                    "Escolha exatamente max_resultados quando houver candidatos suficientes.",
                    "Nao escolha candidatos duplicados.",
                    "Todos os candidatos ja foram filtrados para nao existirem no perfil/grupo.",
                    "Prefira rating alto, muitos reviews, foto, link do Maps e aberto agora.",
                ],
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
            "categoria": place.primary_type,
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
            category=place.primary_type,
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
    return "Boa avaliacao, bom volume de reviews e ainda nao esta salvo neste perfil."

from __future__ import annotations

import asyncio
import logging
from difflib import SequenceMatcher
from typing import Any, AsyncIterator

from app.core.config import Settings
from app.core.errors import ExternalServiceError
from app.integrations.google_places.client import GooglePlacesClient
from app.modules.google_places.schemas import (
    NearbyRestaurant,
    TextSearchRestaurantsRequest,
)
from app.modules.guias_ai.places_cache import TTLCache, normalize_query_key
from app.modules.guias_ai.sanitizer import normalizar_nome
from app.modules.guias_ai.schemas import (
    EnrichedItem,
    ExtractedRestaurant,
    StatusMatching,
)

logger = logging.getLogger(__name__)


class PlacesEnricher:
    """Enrich extracted items via Google Places, with multi-strategy queries."""

    _CATEGORY_HINTS = {
        "hamburgueria": "hamburgueria",
        "hambúrguer": "hamburgueria",
        "burger": "hamburgueria",
        "pizzaria": "pizzaria",
        "pizza": "pizzaria",
        "japones": "japonês",
        "japonês": "japonês",
        "italiano": "italiano",
        "bar": "bar",
        "café": "café",
        "cafe": "café",
        "padaria": "padaria",
        "doceria": "doceria",
        "sorveteria": "sorveteria",
        "bistro": "bistrô",
        "bistrô": "bistrô",
    }

    def __init__(
        self,
        *,
        client: GooglePlacesClient,
        settings: Settings,
        cache: TTLCache[list[NearbyRestaurant]] | None = None,
    ) -> None:
        self._client = client
        self._settings = settings
        self._cache = cache or TTLCache(
            max_entries=settings.guias_ai_places_cache_max_entries,
            ttl_seconds=settings.guias_ai_places_cache_ttl_seconds,
        )

    async def enriquecer_lote(
        self,
        *,
        extracted_items: list[ExtractedRestaurant],
        guide_cidade: str | None,
        guide_categoria: str | None,
        budget: int,
    ) -> tuple[list[EnrichedItem], int, int]:
        """Run enrichment for many items respecting concurrency and total budget.

        Returns (items, calls_done, photos_found).
        """
        if not extracted_items:
            return [], 0, 0

        semaphore = asyncio.Semaphore(self._settings.guias_ai_places_concurrency)
        remaining = budget if budget >= 0 else 0
        # Use a simple counter via list to mutate inside coroutine without locks (single-thread asyncio).
        counters = {"calls": 0, "photos": 0, "remaining": remaining}

        async def task(item: ExtractedRestaurant) -> EnrichedItem:
            async with semaphore:
                if counters["remaining"] <= 0:
                    return EnrichedItem(
                        extracted=item,
                        status_matching=StatusMatching.PENDENTE,
                        alertas=["limite_de_busca_atingido"],
                    )
                used = await self._enrich_one(
                    item=item,
                    guide_cidade=guide_cidade,
                    guide_categoria=guide_categoria,
                )
                counters["calls"] += used.calls
                counters["remaining"] -= used.calls
                if used.enriched.foto_url:
                    counters["photos"] += 1
                return used.enriched

        results = await asyncio.gather(
            *(task(item) for item in extracted_items),
            return_exceptions=False,
        )
        return list(results), counters["calls"], counters["photos"]

    async def enriquecer_streaming(
        self,
        *,
        extracted_items: list[tuple[int, ExtractedRestaurant]],
        guide_cidade: str | None,
        guide_categoria: str | None,
        budget: int,
    ) -> AsyncIterator[tuple[int, EnrichedItem, int, bool]]:
        """Yield (index, enriched_item, calls_used, has_photo) as each task completes.

        The job runner uses this to PATCH each `guia_itens` row independently,
        so the user sees the cards filling in with photos/ratings/etc. as the
        Google calls come back, instead of waiting for the whole batch.
        """
        if not extracted_items:
            return

        semaphore = asyncio.Semaphore(self._settings.guias_ai_places_concurrency)
        counters = {"remaining": budget if budget >= 0 else 0}

        async def task(index: int, item: ExtractedRestaurant) -> tuple[int, EnrichedItem, int, bool]:
            async with semaphore:
                if counters["remaining"] <= 0:
                    enriched = EnrichedItem(
                        extracted=item,
                        status_matching=StatusMatching.PENDENTE,
                        alertas=["limite_de_busca_atingido"],
                    )
                    return index, enriched, 0, False
                outcome = await self._enrich_one(
                    item=item,
                    guide_cidade=guide_cidade,
                    guide_categoria=guide_categoria,
                )
                counters["remaining"] -= outcome.calls
                has_photo = bool(outcome.enriched.foto_url)
                return index, outcome.enriched, outcome.calls, has_photo

        pending = [
            asyncio.create_task(task(index, item))
            for index, item in extracted_items
        ]
        try:
            for finished in asyncio.as_completed(pending):
                yield await finished
        except (asyncio.CancelledError, GeneratorExit):
            for t in pending:
                if not t.done():
                    t.cancel()
            raise

    async def _enrich_one(
        self,
        *,
        item: ExtractedRestaurant,
        guide_cidade: str | None,
        guide_categoria: str | None,
    ) -> "_EnrichOutcome":
        if item.parece_separador or not item.parece_real or item.parece_ruido:
            return _EnrichOutcome(
                enriched=EnrichedItem(
                    extracted=item,
                    status_matching=StatusMatching.IGNORADO,
                    alertas=["ignorado_pelo_extrator"],
                ),
                calls=0,
            )

        queries = self._build_query_variants(
            item=item,
            guide_cidade=guide_cidade,
            guide_categoria=guide_categoria,
        )
        calls = 0
        best_candidate: NearbyRestaurant | None = None
        best_score = 0.0

        for query in queries:
            cache_key = normalize_query_key(query)
            cached = self._cache.get(cache_key)
            if cached is not None:
                candidates = cached
            else:
                calls += 1
                try:
                    candidates = await self._client.search_text_restaurants(
                        TextSearchRestaurantsRequest(
                            text_query=query,
                            page_size=5,
                            included_type="restaurant",
                            strict_type_filtering=False,
                        )
                    )
                except ExternalServiceError as exc:
                    logger.warning(
                        "guias_ai.places_enricher.search_failed query=%s reason=%s",
                        query,
                        exc.message,
                    )
                    continue
                except Exception:  # pragma: no cover - defensivo
                    logger.exception("guias_ai.places_enricher.search_unexpected query=%s", query)
                    continue
                self._cache.set(cache_key, candidates)

            candidate, score = self._best_candidate(item, candidates)
            if candidate and score > best_score:
                best_candidate, best_score = candidate, score

            if best_candidate and best_score >= self._settings.guias_ai_match_strong_score:
                break

        if best_candidate is None:
            return _EnrichOutcome(
                enriched=EnrichedItem(
                    extracted=item,
                    status_matching=StatusMatching.NAO_ENCONTRADO,
                    alertas=["nao_encontrado_no_google"],
                ),
                calls=calls,
            )

        status = self._status_from_score(best_score)
        enriched = self._mapear(item, best_candidate, score=best_score, status=status)
        return _EnrichOutcome(enriched=enriched, calls=calls)

    def _build_query_variants(
        self,
        *,
        item: ExtractedRestaurant,
        guide_cidade: str | None,
        guide_categoria: str | None,
    ) -> list[str]:
        nome = item.nome_original.strip()
        bairro = (item.bairro or "").strip()
        cidade = (item.cidade or guide_cidade or "").strip()
        categoria = self._normalize_category_for_query(item.categoria or guide_categoria)
        unidade = (item.unidade or "").strip()

        variants: list[str] = []

        def add(*parts: str) -> None:
            cleaned = " ".join(p for p in parts if p)
            if cleaned and cleaned not in variants:
                variants.append(cleaned)

        add(nome, unidade, bairro, cidade, categoria)
        add(nome, bairro, cidade, categoria)
        add(nome, cidade, categoria)
        add(nome, cidade)
        add(nome, bairro)
        add(nome, categoria)
        # fallback agressivo: nome puro
        add(nome)

        # variations using simplified name
        nome_simplificado = self._simplify_name(nome)
        if nome_simplificado and nome_simplificado.lower() != nome.lower():
            add(nome_simplificado, cidade, categoria)
            add(nome_simplificado, cidade)

        # cap to keep cost bounded
        return variants[:5]

    def _simplify_name(self, nome: str) -> str:
        # remove common suffixes like "- Filial X", "Unidade X"
        result = nome
        result = result.split(" - ")[0].strip()
        result = result.split(" – ")[0].strip()
        result = result.split(" | ")[0].strip()
        return result

    def _normalize_category_for_query(self, categoria: str | None) -> str:
        if not categoria:
            return "restaurante"
        lower = categoria.lower()
        for hint, canonical in self._CATEGORY_HINTS.items():
            if hint in lower:
                return canonical
        return categoria.strip()

    def _best_candidate(
        self,
        item: ExtractedRestaurant,
        candidates: list[NearbyRestaurant],
    ) -> tuple[NearbyRestaurant | None, float]:
        if not candidates:
            return None, 0.0

        scored: list[tuple[float, NearbyRestaurant]] = []
        for candidate in candidates:
            score = self._score_candidate(item, candidate)
            if score > 0:
                scored.append((score, candidate))

        if not scored:
            return None, 0.0

        scored.sort(key=lambda x: x[0], reverse=True)
        score, candidate = scored[0]
        return candidate, score

    def _score_candidate(
        self,
        item: ExtractedRestaurant,
        candidate: NearbyRestaurant,
    ) -> float:
        norm_extracted = item.nome_normalizado or normalizar_nome(item.nome_original)
        norm_candidate = normalizar_nome(candidate.display_name or "")
        if not norm_extracted or not norm_candidate:
            return 0.0

        nome_score = SequenceMatcher(None, norm_extracted, norm_candidate).ratio()

        cidade_bonus = 0.0
        if item.cidade and candidate.formatted_address:
            cidade_lower = item.cidade.lower()
            address_lower = candidate.formatted_address.lower()
            if cidade_lower in address_lower:
                cidade_bonus += 0.08
        bairro_bonus = 0.0
        if item.bairro and candidate.formatted_address:
            if item.bairro.lower() in candidate.formatted_address.lower():
                bairro_bonus += 0.05

        if (
            len(norm_extracted) >= 4
            and len(norm_candidate) >= 4
            and (norm_extracted in norm_candidate or norm_candidate in norm_extracted)
        ):
            nome_score = max(nome_score, 0.7)

        return min(1.0, nome_score + cidade_bonus + bairro_bonus)

    def _status_from_score(self, score: float) -> StatusMatching:
        if score >= self._settings.guias_ai_match_strong_score:
            return StatusMatching.ENCONTRADO_GOOGLE
        if score >= self._settings.guias_ai_match_weak_score:
            return StatusMatching.BAIXA_CONFIANCA
        return StatusMatching.NAO_ENCONTRADO

    def _mapear(
        self,
        item: ExtractedRestaurant,
        candidate: NearbyRestaurant,
        *,
        score: float,
        status: StatusMatching,
    ) -> EnrichedItem:
        location = candidate.location
        latitude = location.latitude if location else None
        longitude = location.longitude if location else None

        first_attribution = candidate.photo_attributions[0] if candidate.photo_attributions else None
        foto_atribuicao = (
            first_attribution.display_name
            if first_attribution and first_attribution.display_name
            else None
        )

        alertas: list[str] = []
        bs = (candidate.business_status if hasattr(candidate, "business_status") else None)
        if isinstance(bs, str) and bs.upper() not in ("OPERATIONAL", "BUSINESS_STATUS_OPERATIONAL"):
            status = StatusMatching.POSSIVELMENTE_FECHADO
            alertas.append("possivelmente_fechado")

        return EnrichedItem(
            extracted=item,
            place_id=candidate.id or None,
            nome_oficial=candidate.display_name or None,
            endereco=candidate.formatted_address or None,
            latitude=latitude,
            longitude=longitude,
            google_maps_uri=candidate.google_maps_uri or None,
            telefone=candidate.phone_number or None,
            site=candidate.website_uri or None,
            rating=candidate.rating,
            total_avaliacoes=candidate.user_rating_count,
            preco_nivel=_price_level_to_int(candidate.price_level),
            foto_url=getattr(candidate, "photo_uri", None),
            foto_atribuicao=foto_atribuicao,
            status_negocio=getattr(candidate, "business_status", None),
            horarios=[],
            aberto_agora=candidate.open_now,
            categorias_google=[candidate.primary_type] if candidate.primary_type else [],
            confianca_enriquecimento=score,
            status_matching=status,
            score_matching=score,
            alertas=alertas,
        )


class _EnrichOutcome:
    __slots__ = ("enriched", "calls")

    def __init__(self, *, enriched: EnrichedItem, calls: int) -> None:
        self.enriched = enriched
        self.calls = calls


def _price_level_to_int(price_level: Any) -> int | None:
    mapping = {
        "PRICE_LEVEL_FREE": 0,
        "PRICE_LEVEL_INEXPENSIVE": 1,
        "PRICE_LEVEL_MODERATE": 2,
        "PRICE_LEVEL_EXPENSIVE": 3,
        "PRICE_LEVEL_VERY_EXPENSIVE": 4,
    }
    if isinstance(price_level, str):
        return mapping.get(price_level)
    if isinstance(price_level, int):
        return price_level
    return None

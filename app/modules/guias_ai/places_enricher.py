from __future__ import annotations

import asyncio
import logging
import re
from difflib import SequenceMatcher
from typing import Any, AsyncIterator

from app.core.config import Settings
from app.core.errors import ExternalServiceError
from app.integrations.google_places.client import GooglePlacesClient
from app.modules.guias_ai.cost_tracker import CostTracker
from app.modules.google_places.schemas import (
    NearbyRestaurant,
    TextSearchRestaurantsRequest,
)
from app.modules.guias_ai.places_cache import TTLCache, normalize_query_key
from app.modules.guias_ai.query_repairer import PlacesQueryRepairer
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
        query_repairer: PlacesQueryRepairer | None = None,
    ) -> None:
        self._client = client
        self._settings = settings
        self._query_repairer = query_repairer
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
        tracker: CostTracker | None = None,
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
                    tracker=tracker,
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
        tracker: CostTracker | None = None,
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
                    tracker=tracker,
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
        tracker: CostTracker | None = None,
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

        best_candidate, best_score, used_calls = await self._run_search_attempts(
            item=item,
            attempts=self._build_search_attempts(
                queries=queries,
                included_type="restaurant",
            ),
            best_candidate=best_candidate,
            best_score=best_score,
        )
        calls += used_calls

        unfiltered_queries: list[str] = []
        if best_score < self._settings.guias_ai_match_weak_score:
            unfiltered_queries = self._build_unfiltered_query_variants(
                item=item,
                guide_cidade=guide_cidade,
            )
            best_candidate, best_score, used_calls = await self._run_search_attempts(
                item=item,
                attempts=self._build_search_attempts(
                    queries=unfiltered_queries,
                    included_type=None,
                ),
                best_candidate=best_candidate,
                best_score=best_score,
            )
            calls += used_calls

        repair_queries: list[str] = []
        repair_used = False
        if (
            self._query_repairer is not None
            and best_score < self._settings.guias_ai_match_strong_score
        ):
            repair_result = await self._query_repairer.sugerir_queries(
                item=item,
                guide_cidade=guide_cidade,
                guide_categoria=guide_categoria,
                failed_queries=[*queries, *unfiltered_queries],
            )
            if tracker is not None and (
                repair_result.input_tokens or repair_result.output_tokens
            ):
                tracker.record_llm(
                    input_tokens=repair_result.input_tokens,
                    output_tokens=repair_result.output_tokens,
                )
            repair_queries = repair_result.queries
            if repair_queries:
                repair_used = True
                best_candidate, best_score, used_calls = await self._run_search_attempts(
                    item=item,
                    attempts=self._build_search_attempts(
                        queries=repair_queries,
                        included_type=None,
                    ),
                    best_candidate=best_candidate,
                    best_score=best_score,
                )
                calls += used_calls

        if best_candidate is None:
            logger.info(
                "guias_ai.places_enricher.nao_encontrado nome=%s cidade=%s bairro=%s "
                "categoria=%s tentativas=%s chamadas=%s queries=%s repair_queries=%s",
                item.nome_original,
                item.cidade or guide_cidade or "-",
                item.bairro or "-",
                item.categoria or guide_categoria or "-",
                len(queries),
                calls,
                queries[:3],
                repair_queries[:3],
            )
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
        logger.info(
            "guias_ai.places_enricher.matched nome=%s candidate=%s score=%.3f status=%s has_photo=%s has_maps=%s calls=%s",
            item.nome_original,
            best_candidate.display_name,
            best_score,
            status.value,
            bool(enriched.foto_url),
            bool(enriched.google_maps_uri),
            calls,
        )
        if repair_used:
            logger.info(
                "guias_ai.places_enricher.query_repair_matched nome=%s candidate=%s score=%.3f queries=%s",
                item.nome_original,
                best_candidate.display_name,
                best_score,
                repair_queries[:3],
            )
        if status == StatusMatching.BAIXA_CONFIANCA:
            logger.info(
                "guias_ai.places_enricher.baixa_confianca nome=%s candidato=%s score=%.2f",
                item.nome_original,
                best_candidate.display_name or "-",
                best_score,
            )
        if not enriched.foto_url:
            if "google_place_sem_foto" not in enriched.alertas:
                enriched.alertas.append("google_place_sem_foto")
            logger.warning(
                "guias_ai.places_enricher.matched_without_photo nome=%s candidate=%s place_id=%s score=%.3f photos=%s photo_uri=%s",
                item.nome_original,
                best_candidate.display_name,
                best_candidate.id,
                best_score,
                len(best_candidate.photos),
                bool(getattr(best_candidate, "photo_uri", None)),
            )
        return _EnrichOutcome(enriched=enriched, calls=calls)

    async def _search_candidates(
        self,
        *,
        query: str,
        included_type: str | None,
    ) -> tuple[list[NearbyRestaurant], int]:
        cache_key = self._cache_key(query=query, included_type=included_type)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached, 0

        try:
            candidates = await self._client.search_text_restaurants(
                TextSearchRestaurantsRequest(
                    text_query=query,
                    page_size=5,
                    included_type=included_type,
                    strict_type_filtering=False,
                )
            )
        except ExternalServiceError as exc:
            logger.warning(
                "guias_ai.places_enricher.search_failed query=%s included_type=%s reason=%s",
                query,
                included_type,
                exc.message,
            )
            return [], 1
        except Exception:  # pragma: no cover - defensivo
            logger.exception(
                "guias_ai.places_enricher.search_unexpected query=%s included_type=%s",
                query,
                included_type,
            )
            return [], 1

        self._cache.set(cache_key, candidates)
        return candidates, 1

    async def _run_search_attempts(
        self,
        *,
        item: ExtractedRestaurant,
        attempts: list[tuple[str, str | None]],
        best_candidate: NearbyRestaurant | None,
        best_score: float,
    ) -> tuple[NearbyRestaurant | None, float, int]:
        calls = 0
        for query, included_type in attempts:
            candidates, used_call = await self._search_candidates(
                query=query,
                included_type=included_type,
            )
            calls += used_call

            candidate, score = self._best_candidate(item, candidates)
            if candidate and score > best_score:
                best_candidate, best_score = candidate, score

            if best_candidate and best_score >= self._settings.guias_ai_match_strong_score:
                break

        return best_candidate, best_score, calls

    @staticmethod
    def _build_search_attempts(
        *,
        queries: list[str],
        included_type: str | None,
    ) -> list[tuple[str, str | None]]:
        attempts: list[tuple[str, str | None]] = []
        for query in queries:
            query = query.strip()
            entry = (query, included_type)
            if query and entry not in attempts:
                attempts.append(entry)
        return attempts

    def _build_unfiltered_query_variants(
        self,
        *,
        item: ExtractedRestaurant,
        guide_cidade: str | None,
    ) -> list[str]:
        nome = item.nome_original.strip()
        bairro = (item.bairro or "").strip()
        cidade = (item.cidade or guide_cidade or "").strip()
        nome_simplificado = self._simplify_name(nome)

        variants: list[str] = []

        def add(*parts: str) -> None:
            cleaned = " ".join(p for p in parts if p)
            if cleaned and cleaned not in variants:
                variants.append(cleaned)

        add(nome, cidade)
        add(nome, bairro)
        add(nome)
        if nome_simplificado and nome_simplificado.lower() != nome.lower():
            add(nome_simplificado, cidade)
            add(nome_simplificado)

        return variants[:3]

    @staticmethod
    def _cache_key(*, query: str, included_type: str | None) -> str:
        type_key = included_type or "any"
        return normalize_query_key(f"type={type_key} query={query}")

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

        scored: list[tuple[float, int, NearbyRestaurant]] = []
        for candidate in candidates:
            score = self._score_candidate(item, candidate)
            if score > 0:
                reviews = int(candidate.user_rating_count or 0)
                scored.append((score, reviews, candidate))

        if not scored:
            return None, 0.0

        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        top_score = scored[0][0]
        photo_candidates = [
            entry
            for entry in scored
            if getattr(entry[2], "photo_uri", None)
            and entry[0] >= top_score - 0.03
        ]
        if photo_candidates:
            photo_candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
            score, _reviews, candidate = photo_candidates[0]
            return candidate, score

        score, _reviews, candidate = scored[0]
        return candidate, score

    def _score_candidate(
        self,
        item: ExtractedRestaurant,
        candidate: NearbyRestaurant,
    ) -> float:
        norm_candidate = normalizar_nome(candidate.display_name or "")
        if not norm_candidate:
            return 0.0

        nome_score = 0.0
        for alias in self._scoring_name_aliases(item):
            norm_extracted = normalizar_nome(alias)
            if not norm_extracted:
                continue

            alias_score = SequenceMatcher(None, norm_extracted, norm_candidate).ratio()

            if (
                len(norm_extracted) >= 4
                and len(norm_candidate) >= 4
                and (
                    norm_extracted in norm_candidate
                    or norm_candidate in norm_extracted
                )
            ):
                alias_score = max(alias_score, 0.7)

            nome_score = max(nome_score, alias_score)

        if nome_score <= 0:
            return 0.0

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

        return min(1.0, nome_score + cidade_bonus + bairro_bonus)

    def _scoring_name_aliases(self, item: ExtractedRestaurant) -> list[str]:
        aliases: list[str] = []
        seen: set[str] = set()

        def add(value: str | None) -> None:
            if not value:
                return
            cleaned = re.sub(r"\s+", " ", value).strip()
            key = normalizar_nome(cleaned)
            if not key or key in seen:
                return
            seen.add(key)
            aliases.append(cleaned)

        nome = item.nome_original.strip()
        unidade = (item.unidade or "").strip()
        add(nome)
        if unidade:
            add(f"{nome} {unidade}")
            add(unidade)

        parts = [
            part.strip()
            for part in re.split(r"\s(?:-|\u2013|\u2014|\|)\s", nome)
            if part.strip()
        ]
        if len(parts) > 1:
            add(" ".join(parts))
            first_key = normalizar_nome(parts[0])
            if len(first_key) <= 3:
                add(" ".join(parts[1:]))

        return aliases

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

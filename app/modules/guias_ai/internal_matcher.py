from __future__ import annotations

import logging
from difflib import SequenceMatcher
from typing import Any

from app.core.config import Settings
from app.integrations.supabase.client import SupabaseClient
from app.modules.guias_ai.sanitizer import normalizar_nome
from app.modules.guias_ai.schemas import ExtractedRestaurant, StatusMatching

logger = logging.getLogger(__name__)


class InternalMatcher:
    """Match items extracted from AI extractor against existing lugares of the group."""

    def __init__(self, *, client: SupabaseClient, settings: Settings) -> None:
        self._client = client
        self._settings = settings

    async def carregar_inventario(self, *, grupo_id: str) -> list[dict[str, Any]]:
        try:
            rows, _ = await self._client.list_lugares(
                grupo_id=grupo_id,
                select="id,nome,categoria,bairro,cidade,status,favorito,extra,imagem_capa",
                filters=[],
                sort_field="criado_em",
                sort_descending=True,
                page=1,
                page_size=400,
            )
        except Exception:
            logger.exception("guias_ai.internal_matcher.load_failed")
            return []

        inventario: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
            place_id = (
                extra.get("google_place_id")
                or extra.get("place_id")
                or None
            )
            inventario.append(
                {
                    "id": str(row.get("id", "")),
                    "nome": str(row.get("nome", "")),
                    "nome_norm": normalizar_nome(str(row.get("nome", ""))),
                    "categoria": row.get("categoria"),
                    "bairro": row.get("bairro"),
                    "cidade": row.get("cidade"),
                    "status": row.get("status"),
                    "favorito": bool(row.get("favorito") or False),
                    "imagem_capa": row.get("imagem_capa"),
                    "place_id": place_id,
                    "extra": extra,
                    # Latitude/longitude vivem em `extra` quando o lugar foi salvo
                    # via integracao Google. Manter aqui simplifica calculos de
                    # centroide na engine de sugestoes sem expor pra fora do BFF.
                    "latitude": extra.get("latitude") if isinstance(extra, dict) else None,
                    "longitude": extra.get("longitude") if isinstance(extra, dict) else None,
                }
            )
        logger.info(
            "guias_ai.internal_matcher.inventory_loaded grupo_id=%s total=%s",
            grupo_id,
            len(inventario),
        )
        return inventario

    def matchear(
        self,
        *,
        extracted: ExtractedRestaurant,
        inventario: list[dict[str, Any]],
    ) -> tuple[dict[str, Any] | None, float, StatusMatching]:
        if not inventario:
            return None, 0.0, StatusMatching.PENDENTE

        scored: list[tuple[float, dict[str, Any]]] = []
        for lugar in inventario:
            score = self._score(extracted, lugar)
            if score > 0:
                scored.append((score, lugar))

        if not scored:
            return None, 0.0, StatusMatching.PENDENTE

        scored.sort(key=lambda item: item[0], reverse=True)
        best_score, best = scored[0]

        if best_score >= self._settings.guias_ai_match_strong_score:
            return best, best_score, StatusMatching.ENCONTRADO_INTERNO

        if best_score >= self._settings.guias_ai_match_weak_score:
            return best, best_score, StatusMatching.POSSIVEL_DUPLICADO

        return None, best_score, StatusMatching.PENDENTE

    def _score(self, extracted: ExtractedRestaurant, lugar: dict[str, Any]) -> float:
        if not lugar.get("nome_norm") or not extracted.nome_normalizado:
            return 0.0

        nome_score = SequenceMatcher(
            None,
            extracted.nome_normalizado,
            lugar["nome_norm"],
        ).ratio()

        bonus = 0.0
        if extracted.cidade and lugar.get("cidade"):
            if extracted.cidade.strip().lower() == str(lugar["cidade"]).strip().lower():
                bonus += 0.08
        if extracted.bairro and lugar.get("bairro"):
            if extracted.bairro.strip().lower() == str(lugar["bairro"]).strip().lower():
                bonus += 0.06
        if extracted.categoria and lugar.get("categoria"):
            if extracted.categoria.strip().lower() in str(lugar["categoria"]).strip().lower():
                bonus += 0.04

        substring_bonus = 0.0
        if (
            len(extracted.nome_normalizado) >= 4
            and len(lugar["nome_norm"]) >= 4
            and (
                extracted.nome_normalizado in lugar["nome_norm"]
                or lugar["nome_norm"] in extracted.nome_normalizado
            )
        ):
            substring_bonus = 0.05

        return min(1.0, nome_score + bonus + substring_bonus)

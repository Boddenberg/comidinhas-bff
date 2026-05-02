from __future__ import annotations

from app.modules.guias_ai.schemas import EnrichedItem


def escolher_capa(items: list[EnrichedItem]) -> str | None:
    """Pick the best cover image for the guide.

    Strategy:
    1. Best ranked item with a photo and high confidence.
    2. Highest-rated item with a photo.
    3. Any item with a photo.
    """
    if not items:
        return None

    candidates = [item for item in items if item.foto_url]
    if not candidates:
        return None

    candidates.sort(
        key=lambda item: (
            -(item.confianca_enriquecimento or 0.0),
            -(_position_priority(item)),
            -(item.rating or 0.0),
            -(item.total_avaliacoes or 0),
        )
    )
    return candidates[0].foto_url


def _position_priority(item: EnrichedItem) -> float:
    if item.extracted.posicao_ranking is None:
        return 0.0
    # Lower position = higher priority. Invert so smaller is better.
    return 1.0 / (item.extracted.posicao_ranking + 1)

from __future__ import annotations

import json
import logging
import re
import unicodedata
from pathlib import Path
from typing import Any

from app.modules.restaurantes_base.schemas import (
    BuscarRestaurantesBaseRequest,
    BuscarRestaurantesBaseResponse,
    CategoriaBase,
    RestauranteBase,
    RestauranteBaseResultado,
    RestaurantesBaseStats,
)

logger = logging.getLogger(__name__)


class BaseRestaurantesRepository:
    def __init__(self, *, index_path: str) -> None:
        self._index_path = self._resolve_path(index_path)
        self._mtime: float | None = None
        self._versao = "desconhecida"
        self._cidade = "São Paulo"
        self._fonte = ""
        self._restaurantes: list[RestauranteBase] = []
        self._categorias: list[CategoriaBase] = []

    def stats(self) -> RestaurantesBaseStats:
        self._ensure_loaded()
        return RestaurantesBaseStats(
            versao=self._versao,
            cidade=self._cidade,
            fonte=self._fonte,
            total_restaurantes=len(self._restaurantes),
            total_categorias=len(self._categorias),
            categorias=self._categorias,
        )

    def buscar_por_id(self, restaurante_id: str) -> RestauranteBase | None:
        self._ensure_loaded()
        return next(
            (item for item in self._restaurantes if item.id == restaurante_id),
            None,
        )

    def buscar(
        self,
        *,
        request: BuscarRestaurantesBaseRequest,
    ) -> BuscarRestaurantesBaseResponse:
        self._ensure_loaded()
        query_norm = _normalize(request.query)
        query_tokens = _expand_tokens(_tokens(request.query))

        scored: list[tuple[float, RestauranteBase]] = []
        for restaurante in self._restaurantes:
            if request.categoria and not _matches_filter(
                request.categoria,
                [restaurante.categoria, restaurante.categoria_id, restaurante.tipo],
            ):
                continue
            if request.bairro and not _matches_filter(
                request.bairro,
                [restaurante.bairro, restaurante.endereco],
            ):
                continue

            score = _score_restaurante(
                restaurante=restaurante,
                query_norm=query_norm,
                query_tokens=query_tokens,
            )
            if score <= 0:
                continue
            scored.append((score, restaurante))

        scored.sort(key=lambda item: (item[0], item[1].nome.lower()), reverse=True)
        items = [
            RestauranteBaseResultado(
                restaurante=self._copy_for_response(
                    restaurante,
                    incluir_markdown=request.incluir_markdown,
                ),
                score=round(score, 3),
                trechos=_snippets(restaurante, query_tokens=query_tokens),
            )
            for score, restaurante in scored[: request.max_resultados]
        ]
        return BuscarRestaurantesBaseResponse(
            query=request.query,
            total=len(scored),
            items=items,
            versao=self._versao,
            cidade=self._cidade,
        )

    def _ensure_loaded(self) -> None:
        if not self._index_path.exists():
            logger.warning("restaurantes_base.index.not_found path=%s", self._index_path)
            self._mtime = None
            self._restaurantes = []
            self._categorias = []
            return

        mtime = self._index_path.stat().st_mtime
        if self._mtime == mtime:
            return

        payload = json.loads(self._index_path.read_text(encoding="utf-8"))
        restaurantes_raw = payload.get("restaurantes") or []
        categorias_raw = payload.get("categorias") or []
        self._versao = _as_str(payload.get("versao")) or "desconhecida"
        self._cidade = _as_str(payload.get("cidade")) or "São Paulo"
        self._fonte = _as_str(payload.get("fonte")) or ""
        self._restaurantes = [
            RestauranteBase(**item)
            for item in restaurantes_raw
            if isinstance(item, dict) and item.get("id") and item.get("nome")
        ]
        self._categorias = [
            CategoriaBase(**item)
            for item in categorias_raw
            if isinstance(item, dict) and item.get("id")
        ]
        self._mtime = mtime
        logger.info(
            "restaurantes_base.index.loaded path=%s restaurantes=%s categorias=%s",
            self._index_path,
            len(self._restaurantes),
            len(self._categorias),
        )

    @staticmethod
    def _copy_for_response(
        restaurante: RestauranteBase,
        *,
        incluir_markdown: bool,
    ) -> RestauranteBase:
        if incluir_markdown:
            return restaurante
        return restaurante.model_copy(update={"markdown": None})

    @staticmethod
    def _resolve_path(index_path: str) -> Path:
        path = Path(index_path)
        if path.is_absolute():
            return path
        repo_root = Path(__file__).resolve().parents[3]
        return repo_root / path


def _score_restaurante(
    *,
    restaurante: RestauranteBase,
    query_norm: str,
    query_tokens: set[str],
) -> float:
    name_norm = _normalize(restaurante.nome)
    category_norm = _normalize(" ".join([restaurante.categoria, restaurante.tipo or ""]))
    location_norm = _normalize(" ".join([restaurante.bairro or "", restaurante.endereco or ""]))
    description_norm = _normalize(
        " ".join(
            [
                restaurante.descricao or "",
                restaurante.distincao or "",
                restaurante.markdown or "",
            ]
        )
    )
    all_norm = " ".join([name_norm, category_norm, location_norm, description_norm])

    score = 0.0
    if query_norm:
        if query_norm == name_norm:
            score += 40
        elif query_norm in name_norm:
            score += 18
        elif query_norm in all_norm:
            score += 6

    name_tokens = set(_tokens(name_norm))
    category_tokens = set(_tokens(category_norm))
    location_tokens = set(_tokens(location_norm))
    description_tokens = set(_tokens(description_norm))
    indexed_tokens = set(restaurante.termos_busca)

    for token in query_tokens:
        if token in name_tokens:
            score += 7
        elif _has_prefix_match(token, name_tokens):
            score += 3.5

        if token in category_tokens:
            score += 4
        elif _has_prefix_match(token, category_tokens):
            score += 2

        if token in location_tokens:
            score += 3
        elif _has_prefix_match(token, location_tokens):
            score += 1.5

        if token in description_tokens:
            score += 1.4
        elif token in indexed_tokens:
            score += 1

    if restaurante.distincao and query_tokens & {"michelin", "premiado", "premiados", "estrela"}:
        score += 2

    return score


def _snippets(
    restaurante: RestauranteBase,
    *,
    query_tokens: set[str],
) -> list[str]:
    candidates = [
        restaurante.descricao,
        restaurante.distincao,
        restaurante.endereco,
        restaurante.tipo,
    ]
    snippets: list[str] = []
    for value in candidates:
        if not value:
            continue
        normalized = _normalize(value)
        if not query_tokens or any(token in normalized for token in query_tokens):
            snippets.append(value.strip())
        if len(snippets) >= 2:
            break
    return snippets


def _matches_filter(value: str, candidates: list[str | None]) -> bool:
    value_norm = _normalize(value)
    if not value_norm:
        return True
    return any(value_norm in _normalize(candidate) for candidate in candidates if candidate)


def _has_prefix_match(token: str, candidates: set[str]) -> bool:
    return any(
        candidate.startswith(token) or token.startswith(candidate)
        for candidate in candidates
        if len(candidate) >= 4 and len(token) >= 4
    )


def _expand_tokens(tokens: list[str]) -> set[str]:
    expanded = set(tokens)
    for token in list(tokens):
        expanded.update(_SYNONYMS.get(token, set()))
    return expanded


def _tokens(value: str) -> list[str]:
    normalized = _normalize(value)
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return [
        token
        for token in normalized.split()
        if len(token) >= 3 and token not in _STOPWORDS
    ]


def _normalize(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    without_accents = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return " ".join(without_accents.lower().split())


def _as_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


_STOPWORDS = {
    "agora",
    "algo",
    "com",
    "comer",
    "comida",
    "das",
    "dos",
    "estou",
    "hoje",
    "lugar",
    "para",
    "por",
    "quero",
    "restaurante",
    "restaurantes",
    "sem",
    "uma",
    "vontade",
}

_SYNONYMS = {
    "alemao": {"alema"},
    "arabe": {"arabes", "libanesa", "libanes", "medio", "oriente"},
    "brunch": {"cafe", "padaria", "cafeteria"},
    "cafe": {"cafeteria", "padaria", "brunch"},
    "churrasco": {"churrascaria", "steakhouse", "carnes"},
    "coreano": {"coreana", "bom", "retiro"},
    "date": {"romantico", "jantar", "sofisticado"},
    "frutos": {"mar", "peixes", "peixe"},
    "hamburguer": {"hamburgueria", "burger"},
    "indiano": {"indiana"},
    "italiano": {"italiana", "cantina", "trattoria", "osteria"},
    "japones": {"japonesa", "sushi", "omakase", "lamen", "ramen", "izakaya"},
    "japonesa": {"japones", "sushi", "omakase", "lamen", "ramen", "izakaya"},
    "mexicano": {"mexicana", "taco", "tacos"},
    "peruano": {"peruana", "ceviche"},
    "pizza": {"pizzaria", "pizzas"},
    "romantico": {"romantica", "jantar", "sofisticado", "francesa", "italiana"},
    "vegano": {"vegana", "vegetariana", "vegetariano"},
    "vegetariano": {"vegetariana", "vegano", "vegana"},
}

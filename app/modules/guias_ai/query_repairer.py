from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from app.core.config import Settings
from app.core.errors import AppError
from app.integrations.openai.client import OpenAIClient
from app.modules.guias_ai.sanitizer import normalizar_nome
from app.modules.guias_ai.schemas import ExtractedRestaurant

logger = logging.getLogger(__name__)


_QUERY_REPAIR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["queries"],
    "properties": {
        "queries": {
            "type": "array",
            "minItems": 0,
            "maxItems": 5,
            "items": {"type": "string", "minLength": 1, "maxLength": 180},
        },
    },
}

_QUERY_REPAIR_SYSTEM = (
    "Voce ajuda a encontrar restaurantes de guias gastronomicos no Google Maps. "
    "Sua tarefa e apenas reformular termos de busca a partir dos dados recebidos. "
    "Nunca invente restaurantes, enderecos ou franquias. Nunca diga que um lugar foi encontrado. "
    "Retorne somente o JSON no schema exigido."
)


@dataclass(frozen=True)
class QueryRepairResult:
    queries: list[str]
    input_tokens: int = 0
    output_tokens: int = 0


class PlacesQueryRepairer:
    """Suggests better Google Maps text queries for hard-to-match guide items."""

    def __init__(self, *, openai_client: OpenAIClient, settings: Settings) -> None:
        self._openai_client = openai_client
        self._settings = settings

    async def sugerir_queries(
        self,
        *,
        item: ExtractedRestaurant,
        guide_cidade: str | None,
        guide_categoria: str | None,
        failed_queries: list[str],
    ) -> QueryRepairResult:
        if (
            not self._settings.guias_ai_query_repair_enabled
            or not self._settings.is_openai_configured
        ):
            return QueryRepairResult(queries=[])

        prompt = self._build_prompt(
            item=item,
            guide_cidade=guide_cidade,
            guide_categoria=guide_categoria,
            failed_queries=failed_queries,
        )
        try:
            payload, usage = await self._openai_client.chat_json_with_usage(
                prompt=prompt,
                system_prompt=_QUERY_REPAIR_SYSTEM,
                model=self._settings.guias_ai_query_repair_model,
                schema_name="comidinhas_google_maps_query_repair",
                schema=_QUERY_REPAIR_SCHEMA,
            )
        except AppError as exc:
            logger.warning(
                "guias_ai.query_repairer.failed nome=%s reason=%s",
                item.nome_original,
                exc.message,
            )
            return QueryRepairResult(queries=[])
        except Exception:  # pragma: no cover - defensivo
            logger.exception(
                "guias_ai.query_repairer.unexpected nome=%s",
                item.nome_original,
            )
            return QueryRepairResult(queries=[])

        queries = self._sanitize_queries(payload.get("queries"))
        logger.info(
            "guias_ai.query_repairer.suggested nome=%s queries=%s",
            item.nome_original,
            queries,
        )
        return QueryRepairResult(
            queries=queries,
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
        )

    def _build_prompt(
        self,
        *,
        item: ExtractedRestaurant,
        guide_cidade: str | None,
        guide_categoria: str | None,
        failed_queries: list[str],
    ) -> str:
        context = {
            "nome_original": item.nome_original,
            "nome_normalizado": item.nome_normalizado,
            "bairro": item.bairro,
            "cidade": item.cidade,
            "estado": item.estado,
            "categoria": item.categoria,
            "unidade": item.unidade,
            "trecho_original": item.trecho_original,
            "guia_cidade": guide_cidade,
            "guia_categoria": guide_categoria,
            "queries_ja_tentadas": failed_queries[:12],
        }
        return (
            "Gere termos de busca para Google Maps para encontrar o restaurante abaixo.\n"
            "Regras:\n"
            "- Use apenas o nome e o contexto fornecidos.\n"
            "- Se o nome tiver sigla curta e descricao/unidade, combine os dois.\n"
            "- Inclua bairro/cidade quando ajudarem a desambiguar.\n"
            "- Evite query generica, como apenas uma sigla curta, se houver termos mais ricos.\n"
            "- Retorne de 0 a "
            f"{self._settings.guias_ai_query_repair_max_queries} queries, em ordem de prioridade.\n\n"
            "Contexto:\n"
            f"{json.dumps(context, ensure_ascii=False)}"
        )

    def _sanitize_queries(self, raw_queries: Any) -> list[str]:
        if not isinstance(raw_queries, list):
            return []

        result: list[str] = []
        seen: set[str] = set()
        max_queries = self._settings.guias_ai_query_repair_max_queries
        for raw in raw_queries:
            if not isinstance(raw, str):
                continue
            query = re.sub(r"\s+", " ", raw).strip(" \t\r\n\"'")
            if not query:
                continue
            normalized = normalizar_nome(query)
            if len(normalized) < 4:
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            result.append(query[:180])
            if len(result) >= max_queries:
                break
        return result

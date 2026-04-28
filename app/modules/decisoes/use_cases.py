from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.core.errors import BadRequestError, ExternalServiceError, NotFoundError
from app.integrations.openai.client import OpenAIClient
from app.integrations.supabase.client import SupabaseClient
from app.modules.decisoes.schemas import (
    DecidirRestauranteRequest,
    DecidirRestauranteResponse,
    DecisaoRestauranteItem,
    EscopoDecisao,
)
from app.modules.lugares.schemas import LugarResponse
from app.modules.lugares.use_cases import ManageLugaresUseCase

logger = logging.getLogger(__name__)


class DecidirRestauranteUseCase:
    SYSTEM_PROMPT = (
        "Voce e um concierge gastronomico do app Comidinhas. "
        "Escolha um restaurante a partir de candidatos estruturados. "
        "Responda somente JSON valido, sem markdown, sem texto fora do JSON."
    )

    def __init__(
        self,
        *,
        openai_client: OpenAIClient,
        supabase_client: SupabaseClient,
        model: str,
    ) -> None:
        self._openai = openai_client
        self._supabase = supabase_client
        self._model = model

    async def execute(self, *, request: DecidirRestauranteRequest) -> DecidirRestauranteResponse:
        logger.info(
            "decisoes.decidir_restaurante.start grupo_id=%s escopo=%s guia_id=%s",
            request.grupo_id,
            request.escopo.value,
            request.guia_id,
        )
        candidatos = await self._carregar_candidatos(request=request)
        evitar = set(request.evitar_lugar_ids)
        candidatos = [lugar for lugar in candidatos if lugar.id not in evitar]
        logger.info(
            "decisoes.decidir_restaurante.candidatos grupo_id=%s escopo=%s total=%s evitados=%s",
            request.grupo_id,
            request.escopo.value,
            len(candidatos),
            len(evitar),
        )

        if not candidatos:
            raise BadRequestError("Nao ha restaurantes candidatos para este escopo.")

        prompt = self._build_prompt(request=request, candidatos=candidatos)
        raw_reply = await self._openai.chat(
            prompt=prompt,
            system_prompt=self.SYSTEM_PROMPT,
            model=self._model,
        )
        payload = self._parse_json(raw_reply)

        escolha = self._map_item(payload.get("escolha"), candidatos=candidatos)
        alternativas = [
            self._map_item(item, candidatos=candidatos)
            for item in payload.get("alternativas", [])
            if isinstance(item, dict)
        ]
        alternativas = [item for item in alternativas if item.lugar.id != escolha.lugar.id][:3]
        logger.info(
            "decisoes.decidir_restaurante.end grupo_id=%s escopo=%s escolha_lugar_id=%s alternativas=%s",
            request.grupo_id,
            request.escopo.value,
            escolha.lugar.id,
            len(alternativas),
        )

        return DecidirRestauranteResponse(
            grupo_id=request.grupo_id,
            escopo=request.escopo,
            guia_id=request.guia_id,
            escolha=escolha,
            alternativas=alternativas,
            total_candidatos=len(candidatos),
            criterios_usados=request.criterios.model_dump(exclude_none=True),
            modelo=self._model,
        )

    async def _carregar_candidatos(
        self,
        *,
        request: DecidirRestauranteRequest,
    ) -> list[LugarResponse]:
        grupo = await self._supabase.get_grupo(grupo_id=request.grupo_id)
        if grupo is None:
            raise NotFoundError("Grupo nao encontrado.")

        if request.escopo == EscopoDecisao.GUIA:
            return await self._carregar_candidatos_do_guia(request=request)

        filters: list[tuple[str, str]] = []
        if request.escopo == EscopoDecisao.FAVORITOS:
            filters.append(("favorito", "eq.true"))
        elif request.escopo == EscopoDecisao.QUERO_IR:
            filters.append(("status", "eq.quero_ir"))

        rows, _ = await self._supabase.list_lugares(
            grupo_id=request.grupo_id,
            select=ManageLugaresUseCase.SELECT,
            filters=filters,
            sort_field="criado_em",
            sort_descending=True,
            page=1,
            page_size=request.max_candidatos,
        )
        return [ManageLugaresUseCase._mapear(row) for row in rows if isinstance(row, dict)]

    async def _carregar_candidatos_do_guia(
        self,
        *,
        request: DecidirRestauranteRequest,
    ) -> list[LugarResponse]:
        if not request.guia_id:
            raise BadRequestError("Informe guia_id quando escopo='guia'.")

        guia = await self._supabase.get_guia(guia_id=request.guia_id)
        if guia is None:
            raise NotFoundError("Guia nao encontrado.")
        if str(guia.get("grupo_id", "")) != request.grupo_id:
            raise BadRequestError("O guia informado nao pertence ao grupo selecionado.")

        lugar_ids = guia.get("lugar_ids")
        if not isinstance(lugar_ids, list):
            return []

        candidatos: list[LugarResponse] = []
        for lugar_id in lugar_ids[: request.max_candidatos]:
            if not isinstance(lugar_id, str):
                continue
            raw = await self._supabase.get_lugar(
                lugar_id=lugar_id,
                select=ManageLugaresUseCase.SELECT,
            )
            if isinstance(raw, dict):
                candidatos.append(ManageLugaresUseCase._mapear(raw))
        return candidatos

    def _build_prompt(
        self,
        *,
        request: DecidirRestauranteRequest,
        candidatos: list[LugarResponse],
    ) -> str:
        criterios = request.criterios.model_dump(exclude_none=True)
        candidatos_payload = [self._lugar_para_prompt(lugar) for lugar in candidatos]

        return json.dumps(
            {
                "tarefa": "Escolha o melhor restaurante para agora.",
                "regras": [
                    "Use somente lugar_id presente em candidatos.",
                    "Explique o motivo de forma curta e util para o casal/grupo.",
                    "Se orcamento_max existir, evite escolher lugares acima dele, salvo se for muito justificavel.",
                    "Considere mood, clima, dia da semana, ocasiao, preferencias e restricoes quando informados.",
                    "Retorne exatamente um objeto JSON no formato pedido.",
                ],
                "escopo": request.escopo.value,
                "criterios": criterios,
                "formato_resposta": {
                    "escolha": {
                        "lugar_id": "id exato do candidato escolhido",
                        "motivo": "1 a 3 frases",
                        "pontos_fortes": ["ate 3 pontos"],
                        "ressalvas": ["ate 2 ressalvas"],
                        "confianca": 0.0,
                    },
                    "alternativas": [
                        {
                            "lugar_id": "id exato de outro candidato",
                            "motivo": "1 frase",
                            "pontos_fortes": [],
                            "ressalvas": [],
                            "confianca": 0.0,
                        }
                    ],
                },
                "candidatos": candidatos_payload,
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _lugar_para_prompt(lugar: LugarResponse) -> dict[str, Any]:
        return {
            "id": lugar.id,
            "nome": lugar.nome,
            "categoria": lugar.categoria,
            "bairro": lugar.bairro,
            "cidade": lugar.cidade,
            "faixa_preco": lugar.faixa_preco,
            "status": lugar.status.value,
            "favorito": lugar.favorito,
            "notas": _truncate(lugar.notas, limit=500),
            "adicionado_por": lugar.adicionado_por,
            "extra": lugar.extra,
        }

    def _map_item(self, raw: Any, *, candidatos: list[LugarResponse]) -> DecisaoRestauranteItem:
        if not isinstance(raw, dict):
            raise ExternalServiceError("openai", "A IA nao retornou a escolha no formato esperado.")

        lugar_id = raw.get("lugar_id")
        if not isinstance(lugar_id, str):
            raise ExternalServiceError("openai", "A IA nao retornou lugar_id na escolha.")

        lugar = next((item for item in candidatos if item.id == lugar_id), None)
        if lugar is None:
            raise ExternalServiceError("openai", "A IA escolheu um restaurante fora dos candidatos.")

        motivo = raw.get("motivo")
        if not isinstance(motivo, str) or not motivo.strip():
            motivo = "Escolha sugerida pela IA com base nos criterios enviados."

        return DecisaoRestauranteItem(
            lugar=lugar,
            motivo=motivo.strip(),
            pontos_fortes=self._parse_string_list(raw.get("pontos_fortes")),
            ressalvas=self._parse_string_list(raw.get("ressalvas")),
            confianca=self._parse_confidence(raw.get("confianca")),
        )

    @staticmethod
    def _parse_json(raw_text: str) -> dict[str, Any]:
        text = raw_text.strip()
        fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL)
        if fenced:
            text = fenced.group(1).strip()

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ExternalServiceError(
                "openai",
                "A IA retornou uma resposta que nao e JSON valido.",
            ) from exc

        if not isinstance(payload, dict):
            raise ExternalServiceError("openai", "A IA retornou um JSON inesperado.")
        return payload

    @staticmethod
    def _parse_string_list(raw: Any) -> list[str]:
        if not isinstance(raw, list):
            return []
        return [item.strip() for item in raw if isinstance(item, str) and item.strip()][:3]

    @staticmethod
    def _parse_confidence(raw: Any) -> float:
        if isinstance(raw, (int, float)):
            return min(1.0, max(0.0, float(raw)))
        return 0.7


def _truncate(value: str | None, *, limit: int) -> str | None:
    if value is None or len(value) <= limit:
        return value
    return f"{value[:limit].rstrip()}..."

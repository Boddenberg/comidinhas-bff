from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.core.errors import BadRequestError, ExternalServiceError, NotFoundError
from app.integrations.openai.client import OpenAIClient
from app.integrations.supabase.client import SupabaseClient
from app.modules.decisoes import historico
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
        "Escolha um restaurante a partir de candidatos estruturados e escreva "
        "uma justificativa calorosa, pessoal e especifica - como se voce "
        "estivesse falando com um amigo proximo, conectando o lugar ao momento "
        "atual dele (mood, clima, dia, ocasiao, historico recente). "
        "Evite frases genericas como 'boa opcao' ou 'combina com o pedido'. "
        "Responda somente JSON valido, sem markdown, sem texto fora do JSON."
    )
    FONTE = "decidir_restaurante"

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
        contexto = await historico.carregar_contexto(
            supabase_client=self._supabase, grupo_id=request.grupo_id
        )

        evitar_request = set(request.evitar_lugar_ids)
        evitar_dia = contexto.lugares_evitar_dia()
        evitar_semana = contexto.lugares_evitar_semana()

        candidatos_originais = candidatos
        # Hard exclusion: nao repetir nada do dia.
        candidatos = [
            lugar for lugar in candidatos
            if lugar.id not in evitar_request and lugar.id not in evitar_dia
        ]
        # Soft exclusion: tirar tambem o que apareceu na semana, mas com
        # fallback se isso esvaziar a lista.
        if evitar_semana:
            filtrados_semana = [lugar for lugar in candidatos if lugar.id not in evitar_semana]
            if filtrados_semana:
                candidatos = filtrados_semana
            else:
                logger.info(
                    "decisoes.decidir_restaurante.semana_relaxada grupo_id=%s "
                    "candidatos_apos_dia=%s",
                    request.grupo_id,
                    len(candidatos),
                )

        logger.info(
            "decisoes.decidir_restaurante.candidatos grupo_id=%s escopo=%s "
            "total=%s evitados_request=%s evitados_dia=%s evitados_semana=%s "
            "originais=%s",
            request.grupo_id,
            request.escopo.value,
            len(candidatos),
            len(evitar_request),
            len(evitar_dia),
            len(evitar_semana),
            len(candidatos_originais),
        )

        if not candidatos:
            # Se a janela de 24h esvaziou tudo, relaxa pra nao bloquear o usuario.
            candidatos = [
                lugar for lugar in candidatos_originais
                if lugar.id not in evitar_request
            ]
            if not candidatos:
                raise BadRequestError("Nao ha restaurantes candidatos para este escopo.")
            logger.info(
                "decisoes.decidir_restaurante.dia_relaxado grupo_id=%s total=%s",
                request.grupo_id,
                len(candidatos),
            )

        prompt = self._build_prompt(
            request=request, candidatos=candidatos, contexto=contexto
        )
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

        await historico.registrar_sugestoes(
            supabase_client=self._supabase,
            grupo_id=request.grupo_id,
            perfil_id=request.perfil_id,
            fonte=self.FONTE,
            modelo=self._model,
            criterios=request.criterios.model_dump(exclude_none=True),
            sugestoes=[
                self._sugestao_payload(escolha),
                *(self._sugestao_payload(alt) for alt in alternativas),
            ],
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
        contexto: historico.HistoricoContexto,
    ) -> str:
        criterios = request.criterios.model_dump(exclude_none=True)
        candidatos_payload = [self._lugar_para_prompt(lugar) for lugar in candidatos]

        nomes_recentes = [
            sug.nome for sug in contexto.sugestoes if sug.nome
        ][:8]
        personalizacao = contexto.resumo_personalizacao()

        return json.dumps(
            {
                "tarefa": "Escolha o melhor restaurante para agora e explique como se fosse um concierge proximo.",
                "regras": [
                    "Use somente lugar_id presente em candidatos.",
                    "Os candidatos ja foram filtrados para nao repetir restaurantes do dia/semana - prefira de fato variar a escolha.",
                    "Escreva o motivo em primeira pessoa, com 2 a 3 frases, calorosas, especificas e pessoais.",
                    "Conecte explicitamente a escolha ao mood, clima, dia da semana, ocasiao ou historico quando informados.",
                    "Quando fizer sentido, contraste com sugestoes recentes em historico.ultimas (ex: 'depois de tanta comida pesada esta semana, hoje vamos de algo mais leve').",
                    "Liste pontos_fortes que tenham um detalhe sensorial ou pratico (ambiente, prato, bairro, horario), nada generico.",
                    "Se orcamento_max existir, evite escolher lugares acima dele, salvo se for muito justificavel.",
                    "Considere mood, clima, dia da semana, ocasiao, preferencias e restricoes quando informados.",
                    "Retorne exatamente um objeto JSON no formato pedido.",
                ],
                "escopo": request.escopo.value,
                "criterios": criterios,
                "historico": {
                    "ultimas": nomes_recentes,
                    "cozinhas_frequentes": personalizacao.get("cozinhas_frequentes", []),
                    "moods_frequentes": personalizacao.get("moods_frequentes", []),
                    "total_sugestoes_30d": personalizacao.get("total_sugestoes_30d", 0),
                },
                "formato_resposta": {
                    "escolha": {
                        "lugar_id": "id exato do candidato escolhido",
                        "motivo": "2 a 3 frases pessoais, em portugues, conectando lugar ao momento",
                        "pontos_fortes": ["ate 3 pontos especificos"],
                        "ressalvas": ["ate 2 ressalvas"],
                        "confianca": 0.0,
                    },
                    "alternativas": [
                        {
                            "lugar_id": "id exato de outro candidato",
                            "motivo": "1 frase com um angulo diferente",
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

    @staticmethod
    def _sugestao_payload(item: DecisaoRestauranteItem) -> dict[str, Any]:
        extra = item.lugar.extra if isinstance(item.lugar.extra, dict) else {}
        google_place_id = extra.get("google_place_id") if isinstance(extra, dict) else None
        return {
            "nome": item.lugar.nome,
            "lugar_id": item.lugar.id,
            "google_place_id": google_place_id if isinstance(google_place_id, str) else None,
            "origem": "comidinhas",
            "motivo": item.motivo,
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
            motivo = (
                f"Escolhi {lugar.nome} pensando em voces agora - "
                "combina com o momento e ainda nao tinha aparecido por aqui."
            )

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

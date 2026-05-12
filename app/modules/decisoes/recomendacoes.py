from __future__ import annotations

import json
import logging
import unicodedata
from datetime import datetime
from typing import Any

from app.core.errors import ExternalServiceError, NotFoundError
from app.integrations.openai.client import OpenAIClient
from app.integrations.supabase.client import SupabaseClient
from app.modules.decisoes import historico
from app.modules.decisoes.schemas import (
    CandidatoRestaurante,
    EstadoRecomendacao,
    EstrategiaRecomendacao,
    IntencaoPedido,
    InterpretacaoRecomendacao,
    LocalizacaoRecomendacao,
    ModoSugestao,
    OrigemCandidato,
    PreferenciaNovidade,
    RecomendacaoRestauranteItem,
    RecomendarRestaurantesRequest,
    RecomendarRestaurantesResponse,
)
from app.modules.restaurantes_base.repository import BaseRestaurantesRepository
from app.modules.restaurantes_base.schemas import (
    BuscarRestaurantesBaseRequest,
    RestauranteBase,
)
from app.modules.lugares.schemas import LugarResponse, StatusLugar
from app.modules.lugares.use_cases import ManageLugaresUseCase

logger = logging.getLogger(__name__)

_STATUS_VISITADO = {
    StatusLugar.FOMOS,
    StatusLugar.QUERO_VOLTAR,
    StatusLugar.NAO_CURTI,
}

class RecomendarRestaurantesUseCase:
    INTERPRETATION_SYSTEM_PROMPT = (
        "Voce interpreta pedidos gastronomicos do app Comidinhas. "
        "Transforme a mensagem em campos estruturados para busca de restaurantes. "
        "Nao escolha restaurantes nesta etapa."
    )
    RANKING_SYSTEM_PROMPT = (
        "Voce e um concierge gastronomico do app Comidinhas. "
        "Escolha as melhores opcoes entre candidatos estruturados e escreva "
        "uma justificativa pessoal, calorosa e especifica para cada uma, "
        "como se voce conhecesse o gosto deste grupo. "
        "Use somente candidato_id recebido, sem inventar dados externos. "
        "Evite frases genericas como "
        "'combina com o pedido' - destaque um detalhe concreto do lugar e "
        "conecte com o pedido, com o momento ou com o historico recente."
    )
    FONTE = "recomendar_restaurantes"

    INTERPRETATION_SCHEMA: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "intencao": {
                "type": "string",
                "enum": [
                    IntencaoPedido.RECOMENDACAO_RESTAURANTE.value,
                    IntencaoPedido.FORA_ESCOPO.value,
                ],
            },
            "cozinhas": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
            "termos_busca": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
            "momento": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "localizacao_texto": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "estrategia": {
                "type": "string",
                "enum": [
                    EstrategiaRecomendacao.INTERNA.value,
                    EstrategiaRecomendacao.BASE_CONHECIMENTO.value,
                    EstrategiaRecomendacao.HIBRIDA.value,
                ],
            },
            "precisa_localizacao": {"type": "boolean"},
            "preferencia_novidade": {
                "type": "string",
                "enum": [
                    PreferenciaNovidade.AUTO.value,
                    PreferenciaNovidade.NOVO.value,
                    PreferenciaNovidade.SEGURO.value,
                ],
            },
            "preferencias": {"type": "array", "items": {"type": "string"}, "maxItems": 12},
            "restricoes": {"type": "array", "items": {"type": "string"}, "maxItems": 12},
            "orcamento_max": {
                "anyOf": [
                    {"type": "integer", "minimum": 1, "maximum": 4},
                    {"type": "null"},
                ]
            },
            "quantidade_pessoas": {
                "anyOf": [
                    {"type": "integer", "minimum": 1, "maximum": 30},
                    {"type": "null"},
                ]
            },
            "pergunta_refinamento": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "confianca": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": [
            "intencao",
            "cozinhas",
            "termos_busca",
            "momento",
            "localizacao_texto",
            "estrategia",
            "precisa_localizacao",
            "preferencia_novidade",
            "preferencias",
            "restricoes",
            "orcamento_max",
            "quantidade_pessoas",
            "pergunta_refinamento",
            "confianca",
        ],
    }

    RANKING_SCHEMA: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "resumo": {"type": "string"},
            "pergunta_refinamento": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "opcoes": {
                "type": "array",
                "maxItems": 10,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "candidato_id": {"type": "string"},
                        "motivo": {"type": "string"},
                        "pontos_fortes": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 3,
                        },
                        "ressalvas": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 2,
                        },
                        "confianca": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                    "required": [
                        "candidato_id",
                        "motivo",
                        "pontos_fortes",
                        "ressalvas",
                        "confianca",
                    ],
                },
            },
        },
        "required": ["resumo", "pergunta_refinamento", "opcoes"],
    }

    def __init__(
        self,
        *,
        openai_client: OpenAIClient,
        supabase_client: SupabaseClient,
        model: str,
        restaurantes_base: BaseRestaurantesRepository | None = None,
        google_client: Any | None = None,
    ) -> None:
        self._openai = openai_client
        self._restaurantes_base = restaurantes_base
        self._google_client = google_client
        self._supabase = supabase_client
        self._model = model

    async def execute(
        self,
        *,
        request: RecomendarRestaurantesRequest,
    ) -> RecomendarRestaurantesResponse:
        logger.info(
            "recomendacoes.restaurantes.start grupo_id=%s mensagem_len=%s permitir_base=%s permitir_google_legado=%s",
            request.grupo_id,
            len(request.mensagem),
            request.permitir_base_conhecimento,
            request.permitir_google,
        )

        grupo = await self._supabase.get_grupo(grupo_id=request.grupo_id)
        if grupo is None:
            raise NotFoundError("Grupo nao encontrado.")

        contexto = await historico.carregar_contexto(
            supabase_client=self._supabase, grupo_id=request.grupo_id
        )

        interpretacao = await self._interpretar(request=request)
        # Modo explicito do front sobrescreve o que a IA inferiu da mensagem.
        if request.modo == ModoSugestao.DESCOBERTA:
            interpretacao = interpretacao.model_copy(
                update={"preferencia_novidade": PreferenciaNovidade.NOVO}
            )
        elif request.modo == ModoSugestao.CONFORTO:
            interpretacao = interpretacao.model_copy(
                update={"preferencia_novidade": PreferenciaNovidade.SEGURO}
            )
        if interpretacao.intencao == IntencaoPedido.FORA_ESCOPO:
            return self._response_refinamento(
                request=request,
                estado=EstadoRecomendacao.FORA_ESCOPO,
                interpretacao=interpretacao,
                pergunta=interpretacao.pergunta_refinamento
                or "Posso te ajudar a escolher restaurantes, bares ou cafes. O que voce esta com vontade de comer?",
            )

        lugares = await self._carregar_lugares(request=request)
        contexto.lugares_signal = [
            {
                "categoria": lugar.categoria,
                "bairro": lugar.bairro,
                "status": lugar.status.value,
                "favorito": lugar.favorito,
            }
            for lugar in lugares
        ]
        preferencias = contexto.preferencias_inferidas()
        candidatos_internos = [self._candidato_de_lugar(lugar) for lugar in lugares]
        candidatos_internos = self._ordenar_por_score(
            candidatos=candidatos_internos,
            interpretacao=interpretacao,
            preferencias=preferencias,
        )

        deve_buscar_base = self._deve_buscar_base_conhecimento(
            request=request,
            interpretacao=interpretacao,
            candidatos_internos=candidatos_internos,
        )
        candidatos_base: list[CandidatoRestaurante] = []

        if deve_buscar_base:
            candidatos_base = await self._buscar_base_conhecimento(
                request=request,
                interpretacao=interpretacao,
                candidatos_internos=candidatos_internos,
            )

        candidatos = self._ordenar_por_score(
            candidatos=[*candidatos_internos, *candidatos_base],
            interpretacao=interpretacao,
            preferencias=preferencias,
        )
        candidatos = candidatos[: max(12, request.max_resultados * 4)]
        candidatos = self._aplicar_historico(
            candidatos=candidatos,
            contexto=contexto,
            max_resultados=request.max_resultados,
        )
        candidatos = self._aplicar_preferencias_filtragem(
            candidatos=candidatos, preferencias=preferencias
        )

        if not candidatos:
            return self._response_refinamento(
                request=request,
                estado=EstadoRecomendacao.PRECISA_REFINAR,
                interpretacao=interpretacao,
                pergunta="Nao encontrei bons candidatos ainda. Quer me passar uma cidade, bairro ou outro tipo de comida?",
            )

        ranking = await self._ranquear_com_ia(
            request=request,
            interpretacao=interpretacao,
            candidatos=candidatos,
            contexto=contexto,
            preferencias=preferencias,
        )

        fontes = sorted({item.restaurante.origem for item in ranking}, key=lambda item: item.value)
        response = RecomendarRestaurantesResponse(
            grupo_id=request.grupo_id,
            estado=EstadoRecomendacao.OPCOES,
            mensagem=request.mensagem,
            interpretacao=interpretacao,
            resumo=self._ultimo_resumo,
            pergunta_refinamento=self._ultima_pergunta_refinamento,
            opcoes=ranking[: request.max_resultados],
            total_candidatos=len(candidatos),
            fontes_usadas=fontes,
            modelo=self._model,
        )
        logger.info(
            "recomendacoes.restaurantes.end grupo_id=%s opcoes=%s candidatos=%s fontes=%s",
            request.grupo_id,
            len(response.opcoes),
            response.total_candidatos,
            [fonte.value for fonte in response.fontes_usadas],
        )

        persisted = await historico.registrar_sugestoes(
            supabase_client=self._supabase,
            grupo_id=request.grupo_id,
            perfil_id=request.perfil_id,
            fonte=self.FONTE,
            modelo=self._model,
            criterios={
                "mensagem": request.mensagem,
                "cozinhas": interpretacao.cozinhas,
                "preferencias": interpretacao.preferencias,
                "restricoes": interpretacao.restricoes,
                "estrategia": interpretacao.estrategia.value,
                "preferencia_novidade": interpretacao.preferencia_novidade.value,
                "modo": request.modo.value,
            },
            sugestoes=[
                {
                    "nome": item.restaurante.nome,
                    "lugar_id": item.restaurante.lugar_id,
                    "google_place_id": item.restaurante.google_place_id,
                    "origem": item.restaurante.origem.value,
                    "motivo": item.motivo,
                    "categoria": item.restaurante.categoria,
                    "bairro": item.restaurante.bairro,
                }
                for item in response.opcoes
            ],
        )
        self._hidratar_ids(response.opcoes, persistidas=persisted)

        return response

    async def _interpretar(
        self,
        *,
        request: RecomendarRestaurantesRequest,
    ) -> InterpretacaoRecomendacao:
        payload = {
            "mensagem": request.mensagem,
            "data_hora_backend": datetime.now().isoformat(timespec="seconds"),
            "localizacao_recebida": request.localizacao.model_dump(exclude_none=True)
            if request.localizacao
            else None,
            "regras": [
                "Se o usuario pedir comida, restaurante, bar, cafe ou experiencia gastronomica, use intencao recomendacao_restaurante.",
                "Extraia cozinhas como arabe, japones, italiano, indiano, brasileiro, mexicano quando existirem.",
                "Use estrategia hibrida quando fizer sentido combinar lugares salvos e a base de conhecimento local.",
                "Use estrategia base_conhecimento quando o pedido pedir descoberta fora dos lugares ja salvos.",
                "Use preferencia_novidade novo se o usuario pedir algo novo; seguro se pedir sem erro/garantido; auto se nao especificar.",
                "A base de conhecimento cobre restaurantes de Sao Paulo; nao dependa de Google Maps.",
            ],
        }
        raw = await self._openai.chat_json(
            prompt=json.dumps(payload, ensure_ascii=False),
            system_prompt=self.INTERPRETATION_SYSTEM_PROMPT,
            model=self._model,
            schema_name="interpretacao_recomendacao_restaurante",
            schema=self.INTERPRETATION_SCHEMA,
        )
        return InterpretacaoRecomendacao(**raw)

    async def _carregar_lugares(
        self,
        *,
        request: RecomendarRestaurantesRequest,
    ) -> list[LugarResponse]:
        rows, _ = await self._supabase.list_lugares(
            grupo_id=request.grupo_id,
            select=ManageLugaresUseCase.SELECT,
            filters=[],
            sort_field="criado_em",
            sort_descending=True,
            page=1,
            page_size=request.max_candidatos_internos,
        )
        return [ManageLugaresUseCase._mapear(row) for row in rows if isinstance(row, dict)]

    def _deve_buscar_base_conhecimento(
        self,
        *,
        request: RecomendarRestaurantesRequest,
        interpretacao: InterpretacaoRecomendacao,
        candidatos_internos: list[CandidatoRestaurante],
    ) -> bool:
        if self._restaurantes_base is None:
            return False
        if not request.permitir_base_conhecimento:
            return False
        if interpretacao.estrategia in {
            EstrategiaRecomendacao.BASE_CONHECIMENTO,
            EstrategiaRecomendacao.GOOGLE,
            EstrategiaRecomendacao.HIBRIDA,
        }:
            return True
        return len(candidatos_internos) < request.max_resultados or not self._tem_match_interno(
            candidatos=candidatos_internos,
            interpretacao=interpretacao,
        )

    async def _buscar_base_conhecimento(
        self,
        *,
        request: RecomendarRestaurantesRequest,
        interpretacao: InterpretacaoRecomendacao,
        candidatos_internos: list[CandidatoRestaurante],
    ) -> list[CandidatoRestaurante]:
        if self._restaurantes_base is None:
            return []
        query = self._build_base_query(
            mensagem=request.mensagem,
            interpretacao=interpretacao,
            localizacao=request.localizacao,
        )
        response = self._restaurantes_base.buscar(
            request=BuscarRestaurantesBaseRequest(
                query=query,
                bairro=request.localizacao.bairro if request.localizacao else None,
                max_resultados=request.max_candidatos_base_conhecimento,
                incluir_markdown=False,
            )
        )

        nomes_salvos = {_normalize(item.nome) for item in candidatos_internos}

        candidatos: list[CandidatoRestaurante] = []
        for item in response.items:
            restaurante = item.restaurante
            if _normalize(restaurante.nome) in nomes_salvos:
                continue
            candidatos.append(self._candidato_de_base(restaurante))
        return candidatos

    @staticmethod
    def _aplicar_historico(
        *,
        candidatos: list[CandidatoRestaurante],
        contexto: historico.HistoricoContexto,
        max_resultados: int,
    ) -> list[CandidatoRestaurante]:
        if not candidatos:
            return candidatos

        evitar_lugar_dia = contexto.lugares_evitar_dia()
        evitar_google_dia = contexto.google_evitar_dia()
        evitar_lugar_semana = contexto.lugares_evitar_semana()
        evitar_google_semana = contexto.google_evitar_semana()

        def _no_dia(c: CandidatoRestaurante) -> bool:
            return (c.lugar_id and c.lugar_id in evitar_lugar_dia) or (
                c.google_place_id and c.google_place_id in evitar_google_dia
            )

        def _na_semana(c: CandidatoRestaurante) -> bool:
            return (c.lugar_id and c.lugar_id in evitar_lugar_semana) or (
                c.google_place_id and c.google_place_id in evitar_google_semana
            )

        # 24h: hard exclude.
        passo_dia = [c for c in candidatos if not _no_dia(c)]
        # 7d: exclui se ainda sobrar pelo menos max_resultados.
        if any(_na_semana(c) for c in passo_dia):
            passo_semana = [c for c in passo_dia if not _na_semana(c)]
            if len(passo_semana) >= max_resultados:
                return passo_semana
        return passo_dia

    async def _ranquear_com_ia(
        self,
        *,
        request: RecomendarRestaurantesRequest,
        interpretacao: InterpretacaoRecomendacao,
        candidatos: list[CandidatoRestaurante],
        contexto: historico.HistoricoContexto,
        preferencias: historico.PreferenciasInferidas,
    ) -> list[RecomendacaoRestauranteItem]:
        personalizacao = contexto.resumo_personalizacao()
        nomes_recentes = [sug.nome for sug in contexto.sugestoes if sug.nome][:8]

        prompt = json.dumps(
            {
                "pedido_original": request.mensagem,
                "interpretacao": interpretacao.model_dump(mode="json"),
                "max_opcoes": request.max_resultados,
                "regras": [
                    "Use somente candidato_id presente em candidatos.",
                    "Equilibre favoritos/historico com descoberta da base local quando a estrategia for hibrida.",
                    "Se preferencia_novidade for seguro, priorize favoritos, fomos ou quero_voltar.",
                    "Se preferencia_novidade for novo, priorize base_conhecimento ou status quero_ir.",
                    "Evite nao_curti salvo se houver justificativa muito forte.",
                    "Respeite restricoes e orcamento_max quando informados.",
                    "Os candidatos ja foram filtrados para nao repetir o que foi sugerido nas ultimas 24h - nem cite isso na resposta.",
                    "Para cada opcao, escreva 'motivo' com 2 a 3 frases pessoais, em portugues, com um detalhe concreto do lugar e uma conexao com o pedido, com o momento ou com o historico recente. Nada de chavoes como 'combina com o pedido' ou 'boa opcao'.",
                    "Quando fizer sentido, contraste com o historico (ex: 'voces andaram pedindo japones, esta semana topa fugir do padrao com este italiano?').",
                    "O 'resumo' deve ter uma frase calorosa de abertura, em primeira pessoa.",
                    "Nao invente horario, nota, endereco ou preco quando o candidato nao tiver esses campos.",
                ],
                "historico": {
                    "ultimas": nomes_recentes,
                    "cozinhas_frequentes": personalizacao.get("cozinhas_frequentes", []),
                    "moods_frequentes": personalizacao.get("moods_frequentes", []),
                    "total_sugestoes_30d": personalizacao.get("total_sugestoes_30d", 0),
                },
                "preferencias_aprendidas": preferencias.to_prompt(),
                "modo_solicitado": request.modo.value,
                "candidatos": [self._candidato_para_prompt(item) for item in candidatos],
            },
            ensure_ascii=False,
        )

        try:
            raw = await self._openai.chat_json(
                prompt=prompt,
                system_prompt=self.RANKING_SYSTEM_PROMPT,
                model=self._model,
                schema_name="ranking_recomendacao_restaurantes",
                schema=self.RANKING_SCHEMA,
            )
            self._ultimo_resumo = _as_str(raw.get("resumo")) or "Separei algumas opcoes que combinam com o pedido."
            self._ultima_pergunta_refinamento = _as_str(raw.get("pergunta_refinamento"))
            items = self._mapear_ranking(raw.get("opcoes"), candidatos=candidatos)
            if items:
                return items
        except ExternalServiceError:
            raise
        except Exception as exc:
            logger.warning("recomendacoes.ranking.invalid_response error=%s", exc)

        self._ultimo_resumo = "Separei algumas opcoes que combinam com o pedido."
        self._ultima_pergunta_refinamento = None
        return self._ranking_fallback(candidatos=candidatos)

    def _mapear_ranking(
        self,
        raw_items: Any,
        *,
        candidatos: list[CandidatoRestaurante],
    ) -> list[RecomendacaoRestauranteItem]:
        if not isinstance(raw_items, list):
            return []

        por_id = {item.candidato_id: item for item in candidatos}
        result: list[RecomendacaoRestauranteItem] = []
        usados: set[str] = set()

        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            candidato_id = raw.get("candidato_id")
            if not isinstance(candidato_id, str) or candidato_id in usados:
                continue
            candidato = por_id.get(candidato_id)
            if candidato is None:
                continue
            usados.add(candidato_id)
            result.append(
                RecomendacaoRestauranteItem(
                    restaurante=candidato,
                    motivo=_as_str(raw.get("motivo"))
                    or self._motivo_default(candidato),
                    pontos_fortes=_string_list(raw.get("pontos_fortes"), limit=3),
                    ressalvas=_string_list(raw.get("ressalvas"), limit=2),
                    confianca=_confidence(raw.get("confianca")),
                )
            )
        return result

    @staticmethod
    def _motivo_default(candidato: CandidatoRestaurante) -> str:
        partes: list[str] = [f"Pensei em {candidato.nome}"]
        if candidato.bairro:
            partes.append(f"no {candidato.bairro}")
        if candidato.categoria:
            partes.append(f"({candidato.categoria.lower()})")
        prefacio = " ".join(partes)
        if candidato.favorito:
            return f"{prefacio} - ja e favorito de voces e cabe bem no momento."
        if candidato.novo_no_app:
            return f"{prefacio} - opcao nova pra fugir um pouco do padrao."
        return f"{prefacio} - me parece a escolha que mais conversa com o pedido de agora."

    def _ranking_fallback(
        self,
        *,
        candidatos: list[CandidatoRestaurante],
    ) -> list[RecomendacaoRestauranteItem]:
        return [
            RecomendacaoRestauranteItem(
                restaurante=candidato,
                motivo=self._motivo_default(candidato),
                pontos_fortes=self._pontos_fortes_fallback(candidato),
                ressalvas=[],
                confianca=0.62,
            )
            for candidato in candidatos
        ]

    @staticmethod
    def _pontos_fortes_fallback(candidato: CandidatoRestaurante) -> list[str]:
        pontos: list[str] = []
        if candidato.favorito:
            pontos.append("Ja esta nos favoritos")
        if candidato.novo_no_app:
            pontos.append("Opcao nova para descobrir")
        if candidato.rating:
            pontos.append(f"Avaliacao {candidato.rating:.1f}")
        if candidato.origem == OrigemCandidato.BASE_CONHECIMENTO:
            pontos.append("Saiu da base propria do Comidinhas")
        return pontos[:3]

    def _response_refinamento(
        self,
        *,
        request: RecomendarRestaurantesRequest,
        estado: EstadoRecomendacao,
        interpretacao: InterpretacaoRecomendacao,
        pergunta: str,
    ) -> RecomendarRestaurantesResponse:
        return RecomendarRestaurantesResponse(
            grupo_id=request.grupo_id,
            estado=estado,
            mensagem=request.mensagem,
            interpretacao=interpretacao,
            pergunta_refinamento=pergunta,
            modelo=self._model,
        )

    def _candidato_de_lugar(self, lugar: LugarResponse) -> CandidatoRestaurante:
        extra = lugar.extra if isinstance(lugar.extra, dict) else {}
        google_place_id = _as_str(extra.get("google_place_id"))
        return CandidatoRestaurante(
            candidato_id=f"comidinhas:{lugar.id}",
            origem=OrigemCandidato.COMIDINHAS,
            lugar_id=lugar.id,
            google_place_id=google_place_id,
            nome=lugar.nome,
            categoria=lugar.categoria,
            bairro=lugar.bairro,
            cidade=lugar.cidade,
            endereco=_as_str(extra.get("formatted_address")),
            faixa_preco=lugar.faixa_preco,
            rating=_as_float(extra.get("rating")),
            user_rating_count=_as_int(extra.get("user_rating_count")),
            status=lugar.status,
            favorito=lugar.favorito,
            ja_fomos=lugar.status in _STATUS_VISITADO,
            novo_no_app=False,
            aberto_agora=extra.get("open_now") if isinstance(extra.get("open_now"), bool) else None,
            imagem_capa=lugar.imagem_capa,
            fotos=[foto.model_dump(mode="json") for foto in lugar.fotos],
            link=lugar.link,
            google_maps_uri=lugar.link if lugar.link and "google." in lugar.link else None,
            website_uri=_as_str(extra.get("website_uri")),
            telefone=_as_str(extra.get("phone_number")),
        )

    def _candidato_de_base(
        self,
        restaurante: RestauranteBase,
    ) -> CandidatoRestaurante:
        return CandidatoRestaurante(
            candidato_id=f"base:{restaurante.id}",
            origem=OrigemCandidato.BASE_CONHECIMENTO,
            base_restaurante_id=restaurante.id,
            nome=restaurante.nome,
            categoria=restaurante.tipo or restaurante.categoria,
            bairro=restaurante.bairro,
            cidade=restaurante.cidade,
            endereco=restaurante.endereco,
            favorito=False,
            ja_fomos=False,
            novo_no_app=True,
            descricao=restaurante.descricao,
            fonte_chunk=restaurante.fonte_chunk,
        )

    def _ordenar_por_score(
        self,
        *,
        candidatos: list[CandidatoRestaurante],
        interpretacao: InterpretacaoRecomendacao,
        preferencias: historico.PreferenciasInferidas | None = None,
    ) -> list[CandidatoRestaurante]:
        return sorted(
            candidatos,
            key=lambda item: self._score(
                item, interpretacao=interpretacao, preferencias=preferencias
            ),
            reverse=True,
        )

    def _tem_match_interno(
        self,
        *,
        candidatos: list[CandidatoRestaurante],
        interpretacao: InterpretacaoRecomendacao,
    ) -> bool:
        termos = self._termos_relevantes(interpretacao)
        if not termos:
            return bool(candidatos)
        return any(self._score(candidato, interpretacao=interpretacao) > 1 for candidato in candidatos)

    @staticmethod
    def _aplicar_preferencias_filtragem(
        *,
        candidatos: list[CandidatoRestaurante],
        preferencias: historico.PreferenciasInferidas,
    ) -> list[CandidatoRestaurante]:
        if preferencias.is_empty():
            return candidatos
        sem_recusados = [
            c for c in candidatos
            if not (c.lugar_id and c.lugar_id in preferencias.lugares_recusados_ids)
            and not (c.google_place_id and c.google_place_id in preferencias.google_recusados_ids)
        ]
        return sem_recusados or candidatos

    @staticmethod
    def _hidratar_ids(
        items: list[RecomendacaoRestauranteItem],
        *,
        persistidas: list[dict[str, Any]],
    ) -> None:
        if not persistidas:
            return
        por_lugar: dict[str, str] = {}
        por_google: dict[str, str] = {}
        for row in persistidas:
            sugestao_id = row.get("id")
            if not isinstance(sugestao_id, str):
                continue
            lugar_id = row.get("lugar_id")
            google_place_id = row.get("google_place_id")
            if isinstance(lugar_id, str):
                por_lugar.setdefault(lugar_id, sugestao_id)
            if isinstance(google_place_id, str):
                por_google.setdefault(google_place_id, sugestao_id)
        for item in items:
            sugestao_id = None
            if item.restaurante.lugar_id:
                sugestao_id = por_lugar.get(item.restaurante.lugar_id)
            if not sugestao_id and item.restaurante.google_place_id:
                sugestao_id = por_google.get(item.restaurante.google_place_id)
            if sugestao_id:
                item.sugestao_id = sugestao_id

    def _score(
        self,
        candidato: CandidatoRestaurante,
        *,
        interpretacao: InterpretacaoRecomendacao,
        preferencias: historico.PreferenciasInferidas | None = None,
    ) -> float:
        text = _normalize(
            " ".join(
                [
                    candidato.nome,
                    candidato.categoria or "",
                    candidato.bairro or "",
                    candidato.cidade or "",
                    candidato.endereco or "",
                    candidato.descricao or "",
                ]
            )
        )
        score = 0.0
        for termo in self._termos_relevantes(interpretacao):
            normalized = _normalize(termo)
            if normalized and normalized in text:
                score += 3.0

        if candidato.favorito:
            score += 2.0
        if candidato.status == StatusLugar.QUERO_VOLTAR:
            score += 1.8
        if candidato.status == StatusLugar.FOMOS:
            score += 1.0
        if candidato.status == StatusLugar.NAO_CURTI:
            score -= 4.0
        if candidato.aberto_agora:
            score += 0.7
        if candidato.origem == OrigemCandidato.BASE_CONHECIMENTO:
            score += 0.8
        if candidato.rating is not None:
            score += max(0.0, candidato.rating - 3.5)
        if candidato.user_rating_count:
            score += min(1.0, candidato.user_rating_count / 1000)

        if interpretacao.orcamento_max is not None and candidato.faixa_preco is not None:
            if candidato.faixa_preco <= interpretacao.orcamento_max:
                score += 1.0
            else:
                score -= float(candidato.faixa_preco - interpretacao.orcamento_max) * 1.5

        if interpretacao.preferencia_novidade == PreferenciaNovidade.NOVO:
            if candidato.novo_no_app or candidato.status == StatusLugar.QUERO_IR:
                score += 2.5
            if candidato.ja_fomos:
                score -= 1.0
        elif interpretacao.preferencia_novidade == PreferenciaNovidade.SEGURO:
            if candidato.favorito:
                score += 2.5
            if candidato.ja_fomos:
                score += 1.5
            if candidato.novo_no_app:
                score -= 1.5

        if preferencias is not None:
            categoria_norm = (candidato.categoria or "").strip().lower()
            bairro_norm = (candidato.bairro or "").strip().lower()
            if categoria_norm and categoria_norm in preferencias.categorias_aceitas:
                score += 1.5
            if categoria_norm and categoria_norm in preferencias.categorias_recusadas:
                score -= 2.0
            if bairro_norm and bairro_norm in preferencias.bairros_aceitos:
                score += 0.8
            if bairro_norm and bairro_norm in preferencias.bairros_recusados:
                score -= 1.0

        return score

    @staticmethod
    def _termos_relevantes(interpretacao: InterpretacaoRecomendacao) -> list[str]:
        termos = [*interpretacao.cozinhas, *interpretacao.termos_busca, *interpretacao.preferencias]
        result: list[str] = []
        seen: set[str] = set()
        for termo in termos:
            normalized = _normalize(termo)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(termo)
        return result

    @staticmethod
    def _build_base_query(
        *,
        mensagem: str,
        interpretacao: InterpretacaoRecomendacao,
        localizacao: LocalizacaoRecomendacao | None,
    ) -> str:
        termos = [
            *interpretacao.termos_busca,
            *interpretacao.cozinhas,
            *interpretacao.preferencias,
        ]
        base = " ".join(termos[:8]).strip()
        if not base:
            base = mensagem

        local_parts: list[str] = []
        if interpretacao.localizacao_texto:
            local_parts.append(interpretacao.localizacao_texto)
        if localizacao:
            if localizacao.bairro:
                local_parts.append(localizacao.bairro)
            if localizacao.cidade:
                local_parts.append(localizacao.cidade)
        local_text = " ".join(dict.fromkeys(part for part in local_parts if part))
        if local_text and _normalize(local_text) not in _normalize(base):
            return f"{base} em {local_text}"
        return base

    @staticmethod
    def _candidato_para_prompt(candidato: CandidatoRestaurante) -> dict[str, Any]:
        return {
            "candidato_id": candidato.candidato_id,
            "origem": candidato.origem.value,
            "nome": candidato.nome,
            "categoria": candidato.categoria,
            "bairro": candidato.bairro,
            "cidade": candidato.cidade,
            "endereco": candidato.endereco,
            "faixa_preco": candidato.faixa_preco,
            "rating": candidato.rating,
            "user_rating_count": candidato.user_rating_count,
            "status": candidato.status.value if candidato.status else None,
            "favorito": candidato.favorito,
            "ja_fomos": candidato.ja_fomos,
            "novo_no_app": candidato.novo_no_app,
            "aberto_agora": candidato.aberto_agora,
            "descricao": candidato.descricao,
            "fonte_chunk": candidato.fonte_chunk,
        }


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


def _as_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _as_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    return None


def _confidence(value: Any) -> float:
    if isinstance(value, (int, float)):
        return min(1.0, max(0.0, float(value)))
    return 0.7


def _string_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    result = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return result[:limit]

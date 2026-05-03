from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

from app.core.config import Settings
from app.core.errors import ExternalServiceError
from app.integrations.google_places.client import GooglePlacesClient
from app.integrations.openai.client import OpenAIClient
from app.integrations.supabase.client import SupabaseClient
from app.modules.guias_ai.classifier import ContentClassifier
from app.modules.guias_ai.cost_tracker import CostTracker
from app.modules.guias_ai.extractor import GuideExtractor
from app.modules.guias_ai.internal_matcher import InternalMatcher
from app.modules.guias_ai.photo_selector import escolher_capa
from app.modules.guias_ai.places_enricher import PlacesEnricher
from app.modules.guias_ai.sanitizer import (
    detectar_prompt_injection,
    hash_texto,
    normalizar_texto,
    truncar,
)
from app.modules.guias_ai.schemas import (
    EnrichedItem,
    ExtractedGuide,
    JobStatus,
    JOB_PROGRESS,
    JOB_USER_LABEL,
    StatusMatching,
    TipoConteudo,
)
from app.modules.guias_ai.suggestion_engine import SuggestionEngine

logger = logging.getLogger(__name__)


_INVALID_TYPES = {
    TipoConteudo.NAO_GASTRONOMICO,
    TipoConteudo.RECEITA,
    TipoConteudo.INSUFICIENTE,
}


class _JobCancelled(Exception):
    """Raised internally to short-circuit pipeline when user cancels the job."""


class JobRunner:
    """Orchestrates the AI guide creation pipeline against a persisted job row.

    The pipeline is decoupled from the HTTP request and is safe to run in a
    background asyncio task. Every stage updates the job row so the frontend
    can poll for progress, and partial failures never abort the whole import.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        supabase_client: SupabaseClient,
        openai_client: OpenAIClient,
        google_places_client: GooglePlacesClient,
    ) -> None:
        self._settings = settings
        self._supabase = supabase_client
        self._openai = openai_client
        self._google = google_places_client

        self._classifier = ContentClassifier(openai_client=openai_client, settings=settings)
        self._extractor = GuideExtractor(openai_client=openai_client, settings=settings)
        self._internal_matcher = InternalMatcher(client=supabase_client, settings=settings)
        self._places_enricher = PlacesEnricher(client=google_places_client, settings=settings)
        self._suggestion_engine = SuggestionEngine()

    async def executar(self, *, job_id: str) -> None:
        try:
            await asyncio.wait_for(
                self._executar_interno(job_id=job_id),
                timeout=self._settings.guias_ai_job_max_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning("guias_ai.job.timeout job_id=%s", job_id)
            await self._fail(
                job_id=job_id,
                motivo="O processamento ultrapassou o tempo maximo permitido.",
            )
        except _JobCancelled:
            logger.info("guias_ai.job.cancel_observed job_id=%s", job_id)
        except asyncio.CancelledError:
            logger.info("guias_ai.job.task_cancelled job_id=%s", job_id)
            await self._garantir_status_cancelado(job_id=job_id)
            # Nao re-levanta: a task termina graciosamente como cancelada.
            return
        except Exception as exc:  # pragma: no cover - last-resort safety net
            logger.exception("guias_ai.job.unhandled job_id=%s", job_id)
            await self._fail(
                job_id=job_id,
                motivo=f"Falha inesperada no processamento: {type(exc).__name__}",
            )

    async def _garantir_status_cancelado(self, *, job_id: str) -> None:
        try:
            current = await self._supabase.get_guia_ai_job(job_id=job_id)
        except Exception:
            return
        if not isinstance(current, dict):
            return
        if str(current.get("status") or "") == JobStatus.CANCELLED.value:
            return
        try:
            await self._supabase.update_guia_ai_job(
                job_id=job_id,
                payload={
                    "status": JobStatus.CANCELLED.value,
                    "etapa_atual": None,
                    "progresso_percentual": JOB_PROGRESS[JobStatus.CANCELLED],
                    "mensagem_usuario": "Importacao cancelada pelo usuario.",
                    "concluido_em": datetime.now(timezone.utc).isoformat(),
                    "cancelled_em": datetime.now(timezone.utc).isoformat(),
                },
            )
        except Exception:
            logger.exception("guias_ai.job.mark_cancelled_failed job_id=%s", job_id)

    async def _executar_interno(self, *, job_id: str) -> None:
        started_at = time.perf_counter()
        tracker = CostTracker()
        job = await self._supabase.get_guia_ai_job(job_id=job_id)
        if job is None:
            logger.warning("guias_ai.job.missing job_id=%s", job_id)
            return

        resultado = job.get("resultado") if isinstance(job.get("resultado"), dict) else {}
        parent_guia_id = (
            resultado.get("parent_guia_id")
            if isinstance(resultado, dict)
            else None
        )
        if parent_guia_id:
            await self._executar_resumir_guia(
                job=job,
                tracker=tracker,
                started_at=started_at,
            )
            return

        grupo_id = str(job.get("grupo_id", ""))
        perfil_id = str(job.get("perfil_id") or "") or None
        texto_original = str(job.get("texto_original") or "")
        url_origem = job.get("url_origem")
        titulo_sugerido = (job.get("resultado") or {}).get("titulo_sugerido") if isinstance(job.get("resultado"), dict) else None

        await self._update_job_status(
            job_id=job_id,
            status=JobStatus.SANITIZING_TEXT,
            mensagem="Lendo e limpando o texto colado.",
            iniciado_em=datetime.now(timezone.utc).isoformat(),
        )

        texto_normalizado = normalizar_texto(texto_original)
        if not texto_normalizado or len(texto_normalizado) < self._settings.guias_ai_text_min_chars:
            await self._invalid(
                job_id=job_id,
                motivo="texto_curto",
                mensagem="Texto muito curto para gerar um guia.",
            )
            return

        texto_normalizado = truncar(
            texto_normalizado,
            max_chars=self._settings.guias_ai_text_max_chars,
        )
        texto_hash_value = hash_texto(texto_normalizado)
        injection_hits = detectar_prompt_injection(texto_normalizado)
        alertas: list[str] = []
        if injection_hits:
            alertas.append("possivel_prompt_injection")
            logger.info(
                "guias_ai.job.injection_filtered job_id=%s patterns=%s",
                job_id,
                len(injection_hits),
            )

        await self._supabase.update_guia_ai_job(
            job_id=job_id,
            payload={"texto_hash": texto_hash_value, "alertas": alertas},
        )

        # 1. Classificacao
        await self._update_job_status(
            job_id=job_id,
            status=JobStatus.CLASSIFYING_CONTENT,
            mensagem="Avaliando se o texto e gastronomico.",
        )
        classificacao = await self._classifier.classificar(texto_normalizado, tracker=tracker)
        if (
            classificacao.tipo in _INVALID_TYPES
            or (
                classificacao.tipo == TipoConteudo.REVIEW_INDIVIDUAL
                and classificacao.confianca >= 0.65
            )
        ):
            mensagem = self._mensagem_invalido(classificacao)
            await self._invalid(
                job_id=job_id,
                motivo=classificacao.tipo.value,
                mensagem=mensagem,
                detalhe=classificacao.motivo,
            )
            return

        if classificacao.confianca < self._settings.guias_ai_classifier_min_confidence:
            alertas.append("classificacao_baixa_confianca")

        # 2. Extracao de metadados + restaurantes
        await self._update_job_status(
            job_id=job_id,
            status=JobStatus.EXTRACTING_GUIDE_METADATA,
            mensagem="Identificando o guia.",
        )
        extracted = await self._executar_com_retry(
            self._extractor.extrair,
            texto_normalizado,
            etapa="extracao",
            kwargs={"tracker": tracker},
        )
        if extracted is None:
            await self._fail(
                job_id=job_id,
                motivo="A extracao do guia nao retornou um resultado utilizavel.",
            )
            return

        if titulo_sugerido and not extracted.titulo:
            extracted.titulo = str(titulo_sugerido)[:200]

        await self._update_job_status(
            job_id=job_id,
            status=JobStatus.EXTRACTING_RESTAURANTS,
            mensagem="Identificando restaurantes.",
        )

        # Filtra ruido evidente
        candidatos = [
            r
            for r in extracted.restaurantes
            if not r.parece_separador and r.parece_real and not r.parece_ruido
        ]
        if not candidatos:
            await self._invalid(
                job_id=job_id,
                motivo="nenhum_restaurante_identificado",
                mensagem=(
                    "Nao consegui criar um guia porque o texto nao parece conter "
                    "uma lista gastronomica ou restaurantes identificaveis."
                ),
            )
            return

        if len(candidatos) < self._settings.guias_ai_min_items_to_create_guide:
            if classificacao.confianca < 0.6 and extracted.confianca < 0.5:
                await self._invalid(
                    job_id=job_id,
                    motivo="confianca_baixa",
                    mensagem=(
                        "Texto tem poucos restaurantes claros e baixa confianca para "
                        "gerar um guia. Edite o texto e tente novamente."
                    ),
                )
                return
            alertas.append("guia_com_poucos_itens")

        # Limita
        candidatos = candidatos[: self._settings.guias_ai_max_items_per_guide]

        # 2.1 Cria o guia "esqueleto" cedo para que o frontend consiga
        # abrir a pagina enquanto o pipeline ainda enriquece os itens.
        guia_id_parcial = await self._criar_guia_esqueleto(
            grupo_id=grupo_id,
            extracted=extracted,
            url_origem=url_origem,
            titulo_sugerido=titulo_sugerido,
            texto_hash_value=texto_hash_value,
            classificacao=classificacao,
            perfil_id=perfil_id,
        )
        if guia_id_parcial:
            await self._supabase.update_guia_ai_job(
                job_id=job_id,
                payload={"guia_id": guia_id_parcial},
            )

        # 2.2 Insere os itens em DB com dados basicos JA. Isso garante que o
        # usuario abra o guia e veja todos os cards (com nome, posicao, bairro)
        # mesmo antes do enriquecimento por Google completar.
        item_ids: dict[int, str] = {}
        if guia_id_parcial:
            item_ids = await self._inserir_itens_iniciais(
                guia_id=guia_id_parcial,
                candidatos=candidatos,
            )

        # 3. Match interno
        await self._update_job_status(
            job_id=job_id,
            status=JobStatus.MATCHING_INTERNAL_RESTAURANTS,
            mensagem="Cruzando com seus restaurantes.",
        )
        inventario = await self._internal_matcher.carregar_inventario(grupo_id=grupo_id)
        matches: dict[int, tuple[dict[str, Any] | None, float, StatusMatching]] = {}
        for index, restaurant in enumerate(candidatos):
            matches[index] = self._internal_matcher.matchear(
                extracted=restaurant,
                inventario=inventario,
            )

        items_finais: list[EnrichedItem] = [None] * len(candidatos)  # type: ignore[list-item]

        # Itens que ja batem com lugar interno: aplicam-se imediatamente.
        for index, restaurant in enumerate(candidatos):
            internal_lugar, internal_score, internal_status = matches[index]
            if internal_status == StatusMatching.ENCONTRADO_INTERNO and internal_lugar:
                enriched = EnrichedItem(
                    extracted=restaurant,
                    place_id=internal_lugar.get("place_id"),
                    nome_oficial=internal_lugar.get("nome"),
                    bairro_normalizado=internal_lugar.get("bairro"),
                    cidade_normalizada=internal_lugar.get("cidade"),
                    foto_url=internal_lugar.get("imagem_capa"),
                    confianca_enriquecimento=internal_score,
                    status_matching=StatusMatching.ENCONTRADO_INTERNO,
                    score_matching=internal_score,
                    lugar_id=internal_lugar.get("id"),
                    lugar_existente=internal_lugar,
                )
                items_finais[index] = enriched
                await self._patch_item_enriquecido(
                    item_id=item_ids.get(index),
                    item=enriched,
                )

        # 4. Busca/Enriquecimento Google so para itens nao-fortes internamente
        await self._update_job_status(
            job_id=job_id,
            status=JobStatus.SEARCHING_GOOGLE_PLACES,
            mensagem="Buscando dados no Maps.",
        )
        a_enriquecer: list[tuple[int, ExtractedRestaurant]] = [
            (index, restaurant)
            for index, restaurant in enumerate(candidatos)
            if matches[index][2] != StatusMatching.ENCONTRADO_INTERNO
        ]

        calls_done = 0
        photos_found = 0
        if not self._settings.is_google_places_configured:
            alertas.append("google_places_nao_configurado")
            for index, restaurant in a_enriquecer:
                pendente = EnrichedItem(
                    extracted=restaurant,
                    status_matching=StatusMatching.PENDENTE,
                    alertas=["google_places_nao_configurado"],
                )
                items_finais[index] = self._aplicar_match_parcial(
                    pendente, matches[index]
                )
                await self._patch_item_enriquecido(
                    item_id=item_ids.get(index),
                    item=items_finais[index],
                )
        else:
            await self._update_job_status(
                job_id=job_id,
                status=JobStatus.ENRICHING_PLACES,
                mensagem="Enriquecendo dados.",
            )
            stream = self._places_enricher.enriquecer_streaming(
                extracted_items=a_enriquecer,
                guide_cidade=extracted.cidade_principal,
                guide_categoria=extracted.categoria,
                budget=self._settings.guias_ai_max_places_lookups_per_job,
            )
            async for index, enriched, calls, has_photo in stream:
                calls_done += calls
                if calls:
                    tracker.record_google_calls(calls)
                if has_photo:
                    photos_found += 1
                    tracker.record_photo()
                enriched = self._aplicar_match_parcial(enriched, matches[index])
                items_finais[index] = enriched
                await self._patch_item_enriquecido(
                    item_id=item_ids.get(index),
                    item=enriched,
                )

        # Por garantia, preenche qualquer slot que ficou vazio (nao deveria, mas defensivo).
        for index, restaurant in enumerate(candidatos):
            if items_finais[index] is None:
                items_finais[index] = EnrichedItem(
                    extracted=restaurant,
                    status_matching=StatusMatching.PENDENTE,
                    alertas=["nao_processado"],
                )
                await self._patch_item_enriquecido(
                    item_id=item_ids.get(index),
                    item=items_finais[index],
                )

        items_finais = self._deduplicar_por_place_id(items_finais)
        # Propaga os IGNORADO da deduplicacao para o banco.
        for index, item in enumerate(items_finais):
            if item.status_matching == StatusMatching.IGNORADO and item_ids.get(index):
                await self._supabase.update_guia_item(
                    item_id=item_ids[index],
                    payload={
                        "status_matching": StatusMatching.IGNORADO.value,
                        "alertas": [*item.extracted.alertas, *item.alertas],
                    },
                )

        # 4.1 Cria lugares para os matches Google de alta confianca
        # que ainda nao existem no banco interno do grupo.
        lugares_auto_criados: list[str] = []
        if self._settings.guias_ai_auto_create_lugares:
            lugares_auto_criados = await self._auto_criar_lugares(
                grupo_id=grupo_id,
                items=items_finais,
                inventario=inventario,
                item_ids=item_ids,
            )

        # 5. Capa
        await self._update_job_status(
            job_id=job_id,
            status=JobStatus.SELECTING_PHOTOS,
            mensagem="Escolhendo fotos.",
        )
        capa = escolher_capa(items_finais)

        # 6. Sugestoes
        await self._update_job_status(
            job_id=job_id,
            status=JobStatus.CALCULATING_GROUP_SUGGESTIONS,
            mensagem="Calculando sugestoes.",
        )
        membros = await self._coletar_membros_com_cidade(grupo_id=grupo_id)
        sugestoes = self._suggestion_engine.calcular(
            items=items_finais,
            membros=membros,
            inventario_grupo=inventario,
        )

        # 7. Persistencia: cria guia + itens + atualiza ranks
        await self._update_job_status(
            job_id=job_id,
            status=JobStatus.CREATING_GUIDE,
            mensagem="Montando o guia.",
        )

        pendencias = sum(
            1
            for item in items_finais
            if item.status_matching
            in (
                StatusMatching.PENDENTE,
                StatusMatching.NAO_ENCONTRADO,
                StatusMatching.BAIXA_CONFIANCA,
                StatusMatching.POSSIVEL_DUPLICADO,
                StatusMatching.DADOS_INCOMPLETOS,
            )
        )
        matches_internos = sum(
            1
            for item in items_finais
            if item.status_matching == StatusMatching.ENCONTRADO_INTERNO
        )

        qualidade = self._qualidade_geral(
            classificacao_confianca=classificacao.confianca,
            extracao_confianca=extracted.confianca,
            pendencias=pendencias,
            total=len(items_finais),
        )

        nome_guia = (
            extracted.titulo
            or titulo_sugerido
            or f"Guia importado em {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')}"
        )
        nome_guia = nome_guia[:80]

        descricao_guia = extracted.descricao
        if descricao_guia:
            descricao_guia = descricao_guia[:500]

        guia_payload = {
            "nome": nome_guia,
            "descricao": descricao_guia,
            "lugar_ids": [
                item.lugar_id for item in items_finais if item.lugar_id
            ],
            "categoria": extracted.categoria,
            "regiao": extracted.regiao,
            "cidade_principal": extracted.cidade_principal,
            "imagem_capa": capa,
            "total_itens": len(items_finais),
            "status_importacao": (
                "completo"
                if qualidade == "alta" and pendencias == 0
                else "completo_com_alertas"
                if pendencias < len(items_finais)
                else "criado_com_pendencias"
            ),
            "qualidade_importacao": qualidade,
            "alertas": list({*alertas, *self._coletar_alertas(items_finais)}),
            "sugestoes": sugestoes.model_dump(),
        }

        guia_id = guia_id_parcial or ""
        if not guia_id:
            insert_payload = {
                **guia_payload,
                "grupo_id": grupo_id,
                "tipo_guia": "ia",
                "fonte": extracted.fonte,
                "autor": extracted.autor,
                "url_origem": url_origem,
                "data_publicacao": _safe_iso_datetime(extracted.data_publicacao),
                "hash_texto": texto_hash_value,
                "metadados": {
                    "tipo_detectado": classificacao.tipo.value,
                    "tipo_guia_detectado": extracted.tipo_guia_detectado,
                    "quantidade_esperada": extracted.quantidade_esperada,
                    "confianca_classificacao": classificacao.confianca,
                    "confianca_extracao": extracted.confianca,
                    "prompt_version": self._settings.guias_ai_prompt_version,
                    "perfil_id": perfil_id,
                    "url_origem": url_origem,
                },
            }
            try:
                guia_criado = await self._supabase.insert_guia(payload=insert_payload)
            except ExternalServiceError as exc:
                logger.warning("guias_ai.job.create_guia_failed job_id=%s reason=%s", job_id, exc.message)
                await self._fail(
                    job_id=job_id,
                    motivo="Falha ao gravar o guia no banco de dados.",
                )
                return
            guia_id = str(guia_criado.get("id", ""))
        else:
            try:
                await self._supabase.update_guia(guia_id=guia_id, payload=guia_payload)
            except ExternalServiceError as exc:
                logger.warning(
                    "guias_ai.job.update_guia_failed job_id=%s reason=%s",
                    job_id,
                    exc.message,
                )
                alertas.append("falha_ao_atualizar_guia")

        # Os itens ja foram inseridos incrementalmente. Se o guia teve que ser
        # criado tarde (caminho de fallback), faz o bulk insert agora.
        if guia_id and not item_ids:
            itens_payload = [
                self._build_item_payload(guia_id=guia_id, ordem=index, item=item)
                for index, item in enumerate(items_finais)
            ]
            try:
                await self._supabase.insert_guia_itens(items=itens_payload)
            except ExternalServiceError as exc:
                logger.warning(
                    "guias_ai.job.insert_itens_failed job_id=%s reason=%s",
                    job_id,
                    exc.message,
                )
                alertas.append("falha_ao_persistir_itens")

        # 8. Conclusao
        duracao_ms = int((time.perf_counter() - started_at) * 1000)
        cost_snapshot = tracker.snapshot()
        estatisticas = {
            "restaurantes_extraidos": len(extracted.restaurantes),
            "restaurantes_salvos": len(items_finais),
            "matches_internos": matches_internos,
            "buscas_google": calls_done,
            "enriquecidos_google": sum(
                1
                for item in items_finais
                if item.status_matching
                in (
                    StatusMatching.ENCONTRADO_GOOGLE,
                    StatusMatching.BAIXA_CONFIANCA,
                )
            ),
            "fotos_encontradas": photos_found
            + sum(1 for item in items_finais if item.foto_url and item.lugar_existente),
            "pendencias": pendencias,
            "duracao_ms": duracao_ms,
            "chamadas_llm": cost_snapshot["chamadas_llm"],
            "tokens_entrada": cost_snapshot["tokens_entrada"],
            "tokens_saida": cost_snapshot["tokens_saida"],
            "chamadas_google": cost_snapshot["chamadas_google"],
            "custo_estimado_usd": cost_snapshot["custo_estimado_usd"],
            "custo_estimado_brl": cost_snapshot["custo_estimado_brl"],
            "lugares_criados_automaticamente": len(lugares_auto_criados),
        }

        final_status = (
            JobStatus.COMPLETED
            if qualidade == "alta" and pendencias == 0
            else JobStatus.COMPLETED_WITH_WARNINGS
        )

        mensagem_final = self._montar_mensagem_final(
            total=len(items_finais),
            matches_internos=matches_internos,
            enriquecidos=estatisticas["enriquecidos_google"],
            criados_automaticamente=len(lugares_auto_criados),
            pendencias=pendencias,
            tem_capa=bool(capa),
        )

        await self._supabase.update_guia_ai_job(
            job_id=job_id,
            payload={
                "guia_id": guia_id,
                "status": final_status.value,
                "etapa_atual": None,
                "progresso_percentual": JOB_PROGRESS[final_status],
                "concluido_em": datetime.now(timezone.utc).isoformat(),
                "mensagem_usuario": mensagem_final,
                "alertas": list({*alertas, *self._coletar_alertas(items_finais)}),
                "estatisticas": estatisticas,
                "resultado": {
                    "guia_id": guia_id,
                    "qualidade": qualidade,
                    "total_itens": len(items_finais),
                    "lugares_criados_automaticamente": lugares_auto_criados,
                    "resumo": mensagem_final,
                    "stats_resumo": {
                        "identificados": len(items_finais),
                        "ja_no_grupo": matches_internos,
                        "encontrados_google": estatisticas["enriquecidos_google"],
                        "criados_automaticamente": len(lugares_auto_criados),
                        "pendencias": pendencias,
                    },
                },
            },
        )
        logger.info(
            "guias_ai.job.completed job_id=%s guia_id=%s status=%s pendencias=%s duracao_ms=%s",
            job_id,
            guia_id,
            final_status.value,
            pendencias,
            duracao_ms,
        )

    async def _executar_resumir_guia(
        self,
        *,
        job: dict[str, Any],
        tracker: CostTracker,
        started_at: float,
    ) -> None:
        """Resumable retry: only re-enrich items that are still pending.

        Used when a previous job left a partial guide behind (cancelled/failed
        mid-flight). We skip classification and extraction entirely and run
        Google enrichment only on the items whose status_matching is still in
        a non-terminal state.
        """
        job_id = str(job.get("id", ""))
        guia_id = str(job.get("guia_id") or "")
        grupo_id = str(job.get("grupo_id", ""))
        if not guia_id:
            await self._fail(job_id=job_id, motivo="Guia anterior nao encontrado.")
            return

        guia = await self._supabase.get_guia(guia_id=guia_id)
        if guia is None:
            await self._fail(job_id=job_id, motivo="Guia anterior nao existe mais.")
            return

        await self._update_job_status(
            job_id=job_id,
            status=JobStatus.MATCHING_INTERNAL_RESTAURANTS,
            mensagem="Recarregando itens do guia anterior.",
            iniciado_em=datetime.now(timezone.utc).isoformat(),
        )

        rows = await self._supabase.list_guia_itens(guia_id=guia_id)
        if not rows:
            await self._fail(
                job_id=job_id,
                motivo="Guia anterior nao tem itens para reprocessar.",
            )
            return

        pendentes_status = {
            StatusMatching.PENDENTE.value,
            StatusMatching.NAO_ENCONTRADO.value,
            StatusMatching.BAIXA_CONFIANCA.value,
            StatusMatching.DADOS_INCOMPLETOS.value,
        }
        a_enriquecer: list[tuple[int, ExtractedRestaurant, str]] = []
        items_finais: list[EnrichedItem] = []
        item_ids: dict[int, str] = {}

        for row in rows:
            if not isinstance(row, dict):
                continue
            extracted = ExtractedRestaurant(
                posicao_ranking=row.get("posicao_ranking"),
                ordem=int(row.get("ordem") or 0),
                nome_original=str(row.get("nome_importado") or ""),
                nome_normalizado=str(row.get("nome_normalizado") or ""),
                bairro=row.get("bairro"),
                cidade=row.get("cidade"),
                estado=row.get("estado"),
                categoria=row.get("categoria"),
                trecho_original=row.get("trecho_original"),
                confianca_extracao=float(row.get("confianca_extracao") or 0.5),
                alertas=list(row.get("alertas") or []),
            )
            current_status = str(row.get("status_matching") or "pendente")
            index = len(items_finais)
            item_ids[index] = str(row.get("id") or "")

            if current_status in pendentes_status:
                a_enriquecer.append((index, extracted, item_ids[index]))
                items_finais.append(EnrichedItem(extracted=extracted))
            else:
                # Item ja resolvido: preserva o que ja temos.
                try:
                    status_enum = StatusMatching(current_status)
                except ValueError:
                    status_enum = StatusMatching.PENDENTE
                items_finais.append(
                    EnrichedItem(
                        extracted=extracted,
                        place_id=row.get("place_id"),
                        endereco=row.get("endereco"),
                        latitude=row.get("latitude"),
                        longitude=row.get("longitude"),
                        google_maps_uri=row.get("google_maps_uri"),
                        telefone=row.get("telefone"),
                        site=row.get("site"),
                        rating=row.get("rating"),
                        total_avaliacoes=row.get("total_avaliacoes"),
                        preco_nivel=row.get("preco_nivel"),
                        foto_url=row.get("foto_url"),
                        foto_atribuicao=row.get("foto_atribuicao"),
                        confianca_enriquecimento=float(row.get("confianca_enriquecimento") or 0.0),
                        score_matching=float(row.get("score_matching") or 0.0),
                        status_matching=status_enum,
                        lugar_id=row.get("lugar_id"),
                        alertas=list(row.get("alertas") or []),
                    )
                )

        await self._update_job_status(
            job_id=job_id,
            status=JobStatus.SEARCHING_GOOGLE_PLACES,
            mensagem=f"Re-buscando {len(a_enriquecer)} itens pendentes.",
        )

        calls_done = 0
        photos_found = 0
        if a_enriquecer and self._settings.is_google_places_configured:
            stream = self._places_enricher.enriquecer_streaming(
                extracted_items=[(idx, ext) for idx, ext, _ in a_enriquecer],
                guide_cidade=guia.get("cidade_principal"),
                guide_categoria=guia.get("categoria"),
                budget=self._settings.guias_ai_max_places_lookups_per_job,
            )
            async for index, enriched, calls, has_photo in stream:
                calls_done += calls
                if calls:
                    tracker.record_google_calls(calls)
                if has_photo:
                    photos_found += 1
                    tracker.record_photo()
                items_finais[index] = enriched
                await self._patch_item_enriquecido(
                    item_id=item_ids.get(index),
                    item=enriched,
                )

        # Recalcula sugestoes e capa com tudo.
        inventario = await self._internal_matcher.carregar_inventario(grupo_id=grupo_id)
        if self._settings.guias_ai_auto_create_lugares:
            lugares_auto_criados = await self._auto_criar_lugares(
                grupo_id=grupo_id,
                items=items_finais,
                inventario=inventario,
                item_ids=item_ids,
            )
        else:
            lugares_auto_criados = []

        await self._update_job_status(
            job_id=job_id,
            status=JobStatus.SELECTING_PHOTOS,
            mensagem="Atualizando capa.",
        )
        capa = escolher_capa(items_finais) or guia.get("imagem_capa")

        await self._update_job_status(
            job_id=job_id,
            status=JobStatus.CALCULATING_GROUP_SUGGESTIONS,
            mensagem="Recalculando sugestoes.",
        )
        membros = await self._coletar_membros_com_cidade(grupo_id=grupo_id)
        sugestoes = self._suggestion_engine.calcular(
            items=items_finais,
            membros=membros,
            inventario_grupo=inventario,
        )

        pendencias = sum(
            1
            for item in items_finais
            if item.status_matching
            in (
                StatusMatching.PENDENTE,
                StatusMatching.NAO_ENCONTRADO,
                StatusMatching.BAIXA_CONFIANCA,
                StatusMatching.POSSIVEL_DUPLICADO,
                StatusMatching.DADOS_INCOMPLETOS,
            )
        )
        matches_internos = sum(
            1
            for item in items_finais
            if item.status_matching == StatusMatching.ENCONTRADO_INTERNO
        )
        qualidade = self._qualidade_geral(
            classificacao_confianca=0.9,  # parent ja passou pela classificacao
            extracao_confianca=0.9,
            pendencias=pendencias,
            total=len(items_finais),
        )

        await self._supabase.update_guia(
            guia_id=guia_id,
            payload={
                "imagem_capa": capa,
                "total_itens": len(items_finais),
                "status_importacao": (
                    "completo"
                    if pendencias == 0
                    else "completo_com_alertas"
                    if pendencias < len(items_finais)
                    else "criado_com_pendencias"
                ),
                "qualidade_importacao": qualidade,
                "sugestoes": sugestoes.model_dump(),
            },
        )

        duracao_ms = int((time.perf_counter() - started_at) * 1000)
        cost_snapshot = tracker.snapshot()
        final_status = (
            JobStatus.COMPLETED if pendencias == 0 else JobStatus.COMPLETED_WITH_WARNINGS
        )
        mensagem_final = self._montar_mensagem_final(
            total=len(items_finais),
            matches_internos=matches_internos,
            enriquecidos=sum(
                1
                for item in items_finais
                if item.status_matching
                in (StatusMatching.ENCONTRADO_GOOGLE, StatusMatching.BAIXA_CONFIANCA)
            ),
            criados_automaticamente=len(lugares_auto_criados),
            pendencias=pendencias,
            tem_capa=bool(capa),
        )

        await self._supabase.update_guia_ai_job(
            job_id=job_id,
            payload={
                "guia_id": guia_id,
                "status": final_status.value,
                "etapa_atual": None,
                "progresso_percentual": JOB_PROGRESS[final_status],
                "concluido_em": datetime.now(timezone.utc).isoformat(),
                "mensagem_usuario": mensagem_final,
                "estatisticas": {
                    "modo": "resumir",
                    "itens_re_enriquecidos": len(a_enriquecer),
                    "buscas_google": calls_done,
                    "fotos_encontradas": photos_found,
                    "pendencias": pendencias,
                    "duracao_ms": duracao_ms,
                    "lugares_criados_automaticamente": len(lugares_auto_criados),
                    "chamadas_llm": cost_snapshot["chamadas_llm"],
                    "tokens_entrada": cost_snapshot["tokens_entrada"],
                    "tokens_saida": cost_snapshot["tokens_saida"],
                    "chamadas_google": cost_snapshot["chamadas_google"],
                    "custo_estimado_usd": cost_snapshot["custo_estimado_usd"],
                    "custo_estimado_brl": cost_snapshot["custo_estimado_brl"],
                },
            },
        )

    # ---------------------------------------------------------- helpers

    async def _executar_com_retry(self, fn, *args, etapa: str, kwargs: dict | None = None):
        last_error: Exception | None = None
        kwargs = kwargs or {}
        for attempt in range(self._settings.guias_ai_step_max_attempts):
            try:
                return await fn(*args, **kwargs)
            except ExternalServiceError as exc:
                last_error = exc
                logger.warning(
                    "guias_ai.job.retry etapa=%s attempt=%s reason=%s",
                    etapa,
                    attempt + 1,
                    exc.message,
                )
                await asyncio.sleep(min(2 ** attempt, 5))
            except Exception as exc:  # pragma: no cover - defensivo
                last_error = exc
                logger.exception("guias_ai.job.retry_unexpected etapa=%s", etapa)
                await asyncio.sleep(min(2 ** attempt, 5))
        if last_error:
            logger.warning("guias_ai.job.retry_exhausted etapa=%s", etapa)
        return None

    async def _criar_guia_esqueleto(
        self,
        *,
        grupo_id: str,
        extracted: ExtractedGuide,
        url_origem: Any,
        titulo_sugerido: Any,
        texto_hash_value: str,
        classificacao,
        perfil_id: str | None,
    ) -> str | None:
        nome_guia = (
            extracted.titulo
            or (titulo_sugerido if isinstance(titulo_sugerido, str) else None)
            or f"Guia importado em {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')}"
        )[:80]
        descricao = extracted.descricao[:500] if isinstance(extracted.descricao, str) else None

        payload = {
            "grupo_id": grupo_id,
            "nome": nome_guia,
            "descricao": descricao,
            "lugar_ids": [],
            "tipo_guia": "ia",
            "fonte": extracted.fonte,
            "autor": extracted.autor,
            "url_origem": url_origem,
            "data_publicacao": _safe_iso_datetime(extracted.data_publicacao),
            "categoria": extracted.categoria,
            "regiao": extracted.regiao,
            "cidade_principal": extracted.cidade_principal,
            "total_itens": 0,
            "status_importacao": "processando",
            "qualidade_importacao": None,
            "hash_texto": texto_hash_value,
            "alertas": [],
            "sugestoes": {},
            "metadados": {
                "tipo_detectado": classificacao.tipo.value,
                "confianca_classificacao": classificacao.confianca,
                "confianca_extracao": extracted.confianca,
                "prompt_version": self._settings.guias_ai_prompt_version,
                "perfil_id": perfil_id,
                "url_origem": url_origem,
                "construcao": "incremental",
            },
        }
        try:
            criado = await self._supabase.insert_guia(payload=payload)
        except ExternalServiceError as exc:
            logger.warning(
                "guias_ai.job.create_skeleton_failed grupo_id=%s reason=%s",
                grupo_id,
                exc.message,
            )
            return None
        guia_id = str(criado.get("id", "")) or None
        if guia_id:
            logger.info(
                "guias_ai.job.skeleton_created grupo_id=%s guia_id=%s",
                grupo_id,
                guia_id,
            )
        return guia_id

    async def _auto_criar_lugares(
        self,
        *,
        grupo_id: str,
        items: list[EnrichedItem],
        inventario: list[dict[str, Any]],
        item_ids: dict[int, str] | None = None,
    ) -> list[str]:
        existing_place_ids = {
            str(lugar.get("place_id"))
            for lugar in inventario
            if isinstance(lugar, dict) and lugar.get("place_id")
        }
        min_score = self._settings.guias_ai_auto_create_min_score
        criados: list[str] = []
        item_ids = item_ids or {}

        for index, item in enumerate(items):
            if item.lugar_id:
                continue
            if not item.place_id or item.place_id in existing_place_ids:
                continue
            if item.status_matching not in (
                StatusMatching.ENCONTRADO_GOOGLE,
                StatusMatching.BAIXA_CONFIANCA,
            ):
                continue
            if (item.confianca_enriquecimento or 0.0) < min_score:
                continue
            if (item.score_matching or 0.0) < min_score:
                continue

            payload = self._build_lugar_payload(
                grupo_id=grupo_id,
                item=item,
            )
            try:
                criado = await self._supabase.insert_lugar(payload=payload)
            except ExternalServiceError as exc:
                logger.warning(
                    "guias_ai.auto_create_lugar.failed nome=%s reason=%s",
                    item.nome_oficial or item.extracted.nome_original,
                    exc.message,
                )
                continue
            if not isinstance(criado, dict):
                continue
            new_id = str(criado.get("id", ""))
            if not new_id:
                continue
            item.lugar_id = new_id
            item.lugar_existente = criado
            item.status_matching = StatusMatching.CRIADO_AUTOMATICAMENTE
            existing_place_ids.add(item.place_id)
            criados.append(new_id)
            db_item_id = item_ids.get(index)
            if db_item_id:
                try:
                    await self._supabase.update_guia_item(
                        item_id=db_item_id,
                        payload={
                            "lugar_id": new_id,
                            "status_matching": StatusMatching.CRIADO_AUTOMATICAMENTE.value,
                        },
                    )
                except ExternalServiceError as exc:
                    logger.warning(
                        "guias_ai.auto_create_lugar.patch_item_failed item_id=%s reason=%s",
                        db_item_id,
                        exc.message,
                    )
            logger.info(
                "guias_ai.auto_create_lugar.created grupo_id=%s lugar_id=%s place_id=%s",
                grupo_id,
                new_id,
                item.place_id,
            )

        return criados

    @staticmethod
    def _build_lugar_payload(
        *,
        grupo_id: str,
        item: EnrichedItem,
    ) -> dict[str, Any]:
        nome = (item.nome_oficial or item.extracted.nome_original)[:120]
        return {
            "grupo_id": grupo_id,
            "nome": nome,
            "categoria": item.extracted.categoria or item.categorias_google[0]
            if item.categorias_google
            else item.extracted.categoria,
            "bairro": (item.bairro_normalizado or item.extracted.bairro),
            "cidade": (item.cidade_normalizada or item.extracted.cidade),
            "link": item.google_maps_uri,
            "status": "quero_ir",
            "favorito": False,
            "imagem_capa": item.foto_url,
            "fotos": [],
            "extra": {
                "google_place_id": item.place_id,
                "place_id": item.place_id,
                "google_maps_uri": item.google_maps_uri,
                "telefone": item.telefone,
                "site": item.site,
                "rating": item.rating,
                "total_avaliacoes": item.total_avaliacoes,
                "preco_nivel": item.preco_nivel,
                "latitude": item.latitude,
                "longitude": item.longitude,
                "status_negocio": item.status_negocio,
                "categorias_google": item.categorias_google,
                "fonte": "guias_ai_auto",
                "criado_em_iso": datetime.now(timezone.utc).isoformat(),
            },
        }

    async def _inserir_itens_iniciais(
        self,
        *,
        guia_id: str,
        candidatos: list[ExtractedRestaurant],
    ) -> dict[int, str]:
        if not candidatos:
            return {}
        payload = [
            {
                "guia_id": guia_id,
                "ordem": index,
                "posicao_ranking": restaurant.posicao_ranking,
                "nome_importado": restaurant.nome_original[:200],
                "nome_normalizado": restaurant.nome_normalizado,
                "bairro": restaurant.bairro,
                "cidade": restaurant.cidade,
                "estado": restaurant.estado,
                "categoria": restaurant.categoria,
                "trecho_original": restaurant.trecho_original,
                "confianca_extracao": round(restaurant.confianca_extracao, 3),
                "alertas": list(restaurant.alertas),
                "status_matching": StatusMatching.PENDENTE.value,
            }
            for index, restaurant in enumerate(candidatos)
        ]
        try:
            inseridos = await self._supabase.insert_guia_itens(items=payload)
        except ExternalServiceError as exc:
            logger.warning(
                "guias_ai.job.initial_insert_failed guia_id=%s reason=%s",
                guia_id,
                exc.message,
            )
            return {}

        # PostgREST devolve na mesma ordem do envio. Como inserimos por ordem,
        # o indice da lista de retorno casa com o indice do candidato.
        ids: dict[int, str] = {}
        for index, row in enumerate(inseridos):
            if isinstance(row, dict) and row.get("id"):
                ids[index] = str(row["id"])
        logger.info(
            "guias_ai.job.initial_items_inserted guia_id=%s total=%s",
            guia_id,
            len(ids),
        )
        return ids

    async def _patch_item_enriquecido(
        self,
        *,
        item_id: str | None,
        item: EnrichedItem,
    ) -> None:
        if not item_id:
            return
        payload = self._build_item_update_payload(item)
        try:
            await self._supabase.update_guia_item(item_id=item_id, payload=payload)
        except ExternalServiceError as exc:
            logger.warning(
                "guias_ai.job.patch_item_failed item_id=%s reason=%s",
                item_id,
                exc.message,
            )

    @staticmethod
    def _aplicar_match_parcial(
        enriched: EnrichedItem,
        match: tuple[dict[str, Any] | None, float, StatusMatching],
    ) -> EnrichedItem:
        internal_lugar, _internal_score, internal_status = match
        if internal_status == StatusMatching.POSSIVEL_DUPLICADO and internal_lugar:
            enriched.lugar_id = internal_lugar.get("id")
            enriched.lugar_existente = internal_lugar
            if enriched.status_matching not in (
                StatusMatching.NAO_ENCONTRADO,
                StatusMatching.IGNORADO,
            ):
                enriched.status_matching = StatusMatching.POSSIVEL_DUPLICADO
                if "possivel_duplicado_interno" not in enriched.alertas:
                    enriched.alertas.append("possivel_duplicado_interno")
        return enriched

    @staticmethod
    def _build_item_update_payload(item: EnrichedItem) -> dict[str, Any]:
        return {
            "lugar_id": item.lugar_id,
            "place_id": item.place_id,
            "endereco": item.endereco,
            "latitude": item.latitude,
            "longitude": item.longitude,
            "google_maps_uri": item.google_maps_uri,
            "telefone": item.telefone,
            "site": item.site,
            "rating": item.rating,
            "total_avaliacoes": item.total_avaliacoes,
            "preco_nivel": item.preco_nivel,
            "foto_url": item.foto_url,
            "foto_atribuicao": item.foto_atribuicao,
            "status_negocio": item.status_negocio,
            "horarios": item.horarios,
            "status_matching": item.status_matching.value,
            "score_matching": (
                round(item.score_matching, 3) if item.score_matching else None
            ),
            "confianca_enriquecimento": round(item.confianca_enriquecimento, 3),
            "alertas": [*item.extracted.alertas, *item.alertas],
            "extra": {
                "categorias_google": item.categorias_google,
                "aberto_agora": item.aberto_agora,
                "nome_oficial": item.nome_oficial,
            },
        }

    @staticmethod
    def _deduplicar_por_place_id(items: list[EnrichedItem]) -> list[EnrichedItem]:
        seen: dict[str, int] = {}
        for index, item in enumerate(items):
            if not item.place_id:
                continue
            previous_index = seen.get(item.place_id)
            if previous_index is None:
                seen[item.place_id] = index
                continue
            previous = items[previous_index]
            keep_index, drop_index = (
                (previous_index, index)
                if _ranking_key(previous) <= _ranking_key(item)
                else (index, previous_index)
            )
            seen[item.place_id] = keep_index
            dropped = items[drop_index]
            dropped.status_matching = StatusMatching.IGNORADO
            if "duplicado_no_guia" not in dropped.alertas:
                dropped.alertas.append("duplicado_no_guia")
        return items

    async def _coletar_membros_com_cidade(self, *, grupo_id: str) -> list[dict[str, Any]]:
        try:
            grupo = await self._supabase.get_grupo(grupo_id=grupo_id)
        except Exception:
            logger.exception("guias_ai.job.get_grupo_failed grupo_id=%s", grupo_id)
            return []
        if not isinstance(grupo, dict):
            return []
        membros = grupo.get("membros") if isinstance(grupo.get("membros"), list) else []
        result: list[dict[str, Any]] = []
        for membro in membros:
            if not isinstance(membro, dict):
                continue
            perfil_id = membro.get("perfil_id")
            cidade_membro: str | None = None
            if isinstance(perfil_id, str) and perfil_id:
                try:
                    perfil = await self._supabase.get_perfil(perfil_id=perfil_id)
                except Exception:
                    perfil = None
                if isinstance(perfil, dict):
                    cidade_perfil = perfil.get("cidade")
                    if isinstance(cidade_perfil, str) and cidade_perfil.strip():
                        cidade_membro = cidade_perfil.strip()
            result.append(
                {
                    "perfil_id": perfil_id,
                    "cidade": cidade_membro,
                }
            )
        return result

    async def _update_job_status(
        self,
        *,
        job_id: str,
        status: JobStatus,
        mensagem: str | None = None,
        iniciado_em: str | None = None,
    ) -> None:
        if await self._is_cancelled(job_id=job_id):
            raise _JobCancelled()

        payload: dict[str, Any] = {
            "status": status.value,
            "etapa_atual": JOB_USER_LABEL.get(status, status.value),
            "progresso_percentual": JOB_PROGRESS.get(status, 0),
        }
        if mensagem:
            payload["mensagem_usuario"] = mensagem
        if iniciado_em:
            payload["iniciado_em"] = iniciado_em
        await self._supabase.update_guia_ai_job(job_id=job_id, payload=payload)

    async def _is_cancelled(self, *, job_id: str) -> bool:
        try:
            current = await self._supabase.get_guia_ai_job(job_id=job_id)
        except Exception:
            return False
        if not isinstance(current, dict):
            return False
        return str(current.get("status") or "") == JobStatus.CANCELLED.value

    async def _invalid(
        self,
        *,
        job_id: str,
        motivo: str,
        mensagem: str,
        detalhe: str | None = None,
    ) -> None:
        await self._supabase.update_guia_ai_job(
            job_id=job_id,
            payload={
                "status": JobStatus.INVALID_CONTENT.value,
                "etapa_atual": None,
                "progresso_percentual": JOB_PROGRESS[JobStatus.INVALID_CONTENT],
                "motivo_invalido": motivo,
                "mensagem_usuario": mensagem,
                "concluido_em": datetime.now(timezone.utc).isoformat(),
                "alertas": [a for a in [detalhe] if a],
            },
        )
        logger.info(
            "guias_ai.job.invalid job_id=%s motivo=%s",
            job_id,
            motivo,
        )

    async def _fail(self, *, job_id: str, motivo: str) -> None:
        await self._supabase.update_guia_ai_job(
            job_id=job_id,
            payload={
                "status": JobStatus.FAILED.value,
                "etapa_atual": None,
                "progresso_percentual": JOB_PROGRESS[JobStatus.FAILED],
                "mensagem_usuario": motivo,
                "concluido_em": datetime.now(timezone.utc).isoformat(),
            },
        )

    @staticmethod
    def _build_item_payload(*, guia_id: str, ordem: int, item: EnrichedItem) -> dict[str, Any]:
        extracted = item.extracted
        return {
            "guia_id": guia_id,
            "lugar_id": item.lugar_id,
            "posicao_ranking": extracted.posicao_ranking,
            "ordem": ordem,
            "nome_importado": extracted.nome_original,
            "nome_normalizado": extracted.nome_normalizado,
            "bairro": item.bairro_normalizado or extracted.bairro,
            "cidade": item.cidade_normalizada or extracted.cidade,
            "estado": extracted.estado,
            "categoria": extracted.categoria,
            "place_id": item.place_id,
            "endereco": item.endereco,
            "latitude": item.latitude,
            "longitude": item.longitude,
            "google_maps_uri": item.google_maps_uri,
            "telefone": item.telefone,
            "site": item.site,
            "rating": item.rating,
            "total_avaliacoes": item.total_avaliacoes,
            "preco_nivel": item.preco_nivel,
            "foto_url": item.foto_url,
            "foto_atribuicao": item.foto_atribuicao,
            "status_negocio": item.status_negocio,
            "horarios": item.horarios,
            "status_matching": item.status_matching.value,
            "score_matching": round(item.score_matching, 3) if item.score_matching else None,
            "confianca_extracao": round(extracted.confianca_extracao, 3),
            "confianca_enriquecimento": round(item.confianca_enriquecimento, 3),
            "alertas": [*extracted.alertas, *item.alertas],
            "trecho_original": extracted.trecho_original,
            "extra": {
                "categorias_google": item.categorias_google,
                "aberto_agora": item.aberto_agora,
                "nome_oficial": item.nome_oficial,
            },
        }

    @staticmethod
    def _montar_mensagem_final(
        *,
        total: int,
        matches_internos: int,
        enriquecidos: int,
        criados_automaticamente: int,
        pendencias: int,
        tem_capa: bool,
    ) -> str:
        if total == 0:
            return "Nao consegui identificar restaurantes neste texto."

        partes = [f"Seu guia foi criado com {total} restaurantes."]
        if matches_internos:
            partes.append(
                f"{matches_internos} ja estavam no Comidinhas."
            )
        if enriquecidos:
            partes.append(
                f"{enriquecidos} foram enriquecidos pelo Google Maps."
            )
        if criados_automaticamente:
            partes.append(
                f"Adicionamos {criados_automaticamente} novos restaurantes ao seu grupo."
            )
        if pendencias:
            partes.append(
                f"{pendencias} {'precisa' if pendencias == 1 else 'precisam'} de revisao."
            )
        if tem_capa:
            partes.append("Foto de capa adicionada automaticamente.")
        return " ".join(partes)

    @staticmethod
    def _coletar_alertas(items: list[EnrichedItem]) -> list[str]:
        alertas: set[str] = set()
        for item in items:
            for alerta in item.alertas:
                if alerta:
                    alertas.add(f"item:{alerta}")
        return sorted(alertas)

    @staticmethod
    def _qualidade_geral(
        *,
        classificacao_confianca: float,
        extracao_confianca: float,
        pendencias: int,
        total: int,
    ) -> str:
        if total == 0:
            return "baixa"
        ratio_pendencias = pendencias / total
        if (
            classificacao_confianca >= 0.7
            and extracao_confianca >= 0.6
            and ratio_pendencias <= 0.15
        ):
            return "alta"
        if classificacao_confianca >= 0.5 and ratio_pendencias <= 0.4:
            return "media"
        return "baixa"

    @staticmethod
    def _mensagem_invalido(classificacao) -> str:
        match classificacao.tipo:
            case TipoConteudo.NAO_GASTRONOMICO:
                return (
                    "Nao consegui criar um guia porque o texto nao parece conter "
                    "uma lista gastronomica ou restaurantes identificaveis."
                )
            case TipoConteudo.RECEITA:
                return (
                    "O texto parece ser uma receita culinaria, nao um guia de restaurantes."
                )
            case TipoConteudo.REVIEW_INDIVIDUAL:
                return (
                    "Este texto parece falar de um unico restaurante. "
                    "Voce pode salva-lo como restaurante individual."
                )
            case TipoConteudo.INSUFICIENTE:
                return "O texto colado e curto demais para gerar um guia."
            case _:
                return "Nao consegui criar um guia a partir desse texto."


def _ranking_key(item: EnrichedItem) -> tuple[int, float]:
    posicao = item.extracted.posicao_ranking
    return (
        posicao if posicao is not None else 9_999,
        -float(item.score_matching or 0.0),
    )


def _safe_iso_datetime(value: str | None) -> str | None:
    if not value or not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned[:50]

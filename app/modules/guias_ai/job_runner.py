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
    ExtractedRestaurant,
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

        # Filosofia: capturar tudo que o cliente colou. So descartamos "separadores"
        # (titulos de secao do texto, tipo "TOP 20"), que nao sao restaurantes.
        # Itens marcados como ruido/baixa confianca pelo extrator entram com alertas
        # para o usuario revisar — preferimos um falso positivo a perder um item real.
        total_extraidos = len(extracted.restaurantes)
        candidatos: list[ExtractedRestaurant] = []
        descartados_separador = 0
        sinalizados_ruido = 0
        sinalizados_baixa_confianca = 0
        descartes_log: list[dict[str, Any]] = []

        for r in extracted.restaurantes:
            if r.parece_separador:
                descartados_separador += 1
                if len(descartes_log) < 50:
                    descartes_log.append(
                        {"nome": r.nome_original, "motivo": "parece_separador"}
                    )
                continue
            if r.parece_ruido and "extrator_marcou_como_ruido" not in r.alertas:
                r.alertas.append("extrator_marcou_como_ruido")
                sinalizados_ruido += 1
            if not r.parece_real and "extrator_baixa_confianca" not in r.alertas:
                r.alertas.append("extrator_baixa_confianca")
                sinalizados_baixa_confianca += 1
            candidatos.append(r)

        logger.info(
            "guias_ai.job.candidatos_filtro job_id=%s extraidos=%s mantidos=%s "
            "separadores=%s ruido_sinalizado=%s baixa_confianca_sinalizada=%s "
            "tipo=%s confianca_extracao=%.2f confianca_classificacao=%.2f",
            job_id,
            total_extraidos,
            len(candidatos),
            descartados_separador,
            sinalizados_ruido,
            sinalizados_baixa_confianca,
            extracted.tipo_guia_detectado or "desconhecido",
            extracted.confianca,
            classificacao.confianca,
        )
        if descartes_log:
            logger.info(
                "guias_ai.job.itens_descartados job_id=%s descartes=%s",
                job_id,
                descartes_log,
            )

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

        # Limita ao maximo configurado por guia (no caso de textos com centenas de itens).
        if len(candidatos) > self._settings.guias_ai_max_items_per_guide:
            logger.info(
                "guias_ai.job.candidatos_truncados job_id=%s antes=%s depois=%s",
                job_id,
                len(candidatos),
                self._settings.guias_ai_max_items_per_guide,
            )
            alertas.append("guia_truncado_por_limite")
            candidatos = candidatos[: self._settings.guias_ai_max_items_per_guide]

        # Identifica se e um ranking explicito para preservar a ordem do usuario.
        # Sinais: tipo_guia_detectado=="ranking" OU pelo menos metade dos itens
        # tem posicao_ranking explicita.
        com_ranking = sum(1 for r in candidatos if r.posicao_ranking is not None)
        is_ranking = (extracted.tipo_guia_detectado or "").strip().lower() == "ranking" or (
            len(candidatos) > 0 and com_ranking >= max(2, len(candidatos) // 2)
        )
        if is_ranking:
            # Ranking: ordena por posicao_ranking, com fallback para a ordem do
            # texto. Itens sem posicao vao depois dos que tem, preservando contexto.
            candidatos.sort(
                key=lambda r: (
                    r.posicao_ranking if r.posicao_ranking is not None else 10_000 + r.ordem,
                    r.ordem,
                )
            )
        # Caso contrario, mantem a ordem do texto original (ordem 0..n vinda do LLM).
        logger.info(
            "guias_ai.job.ordem_detectada job_id=%s is_ranking=%s itens_com_posicao=%s/%s "
            "tipo_guia_detectado=%s",
            job_id,
            is_ranking,
            com_ranking,
            len(candidatos),
            extracted.tipo_guia_detectado or "desconhecido",
        )

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
            is_ranking=is_ranking,
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
        initial_items_insert_attempted = False
        if guia_id_parcial:
            initial_items_insert_attempted = True
            item_ids = await self._inserir_itens_iniciais(
                guia_id=guia_id_parcial,
                candidatos=candidatos,
            )
            logger.info(
                "guias_ai.job.initial_item_id_coverage job_id=%s guia_id=%s candidatos=%s ids=%s missing=%s",
                job_id,
                guia_id_parcial,
                len(candidatos),
                len(item_ids),
                len(candidatos) - len(item_ids),
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
                enriched = self._build_internal_enriched_item(
                    restaurant=restaurant,
                    internal_lugar=internal_lugar,
                    internal_score=internal_score,
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
            or self._needs_google_hydration(items_finais[index])
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
                logger.info(
                    "guias_ai.job.google_item_result job_id=%s index=%s ordem=%s nome=%s status=%s has_photo=%s has_maps=%s calls=%s internal_status=%s",
                    job_id,
                    index,
                    enriched.extracted.ordem,
                    enriched.extracted.nome_original[:80],
                    enriched.status_matching.value,
                    bool(enriched.foto_url),
                    bool(enriched.google_maps_uri),
                    calls,
                    matches[index][2].value,
                )
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
                    "is_ranking": is_ranking,
                    "ordem_origem": "ranking" if is_ranking else "texto_original",
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
        if guia_id:
            item_ids = await self._persistir_itens_finais(
                job_id=job_id,
                guia_id=guia_id,
                item_ids=item_ids,
                items_finais=items_finais,
                initial_items_insert_attempted=initial_items_insert_attempted,
                alertas=alertas,
            )

        # 8. Conclusao
        duracao_ms = int((time.perf_counter() - started_at) * 1000)
        cost_snapshot = tracker.snapshot()
        nao_encontrados_google = sum(
            1
            for item in items_finais
            if item.status_matching == StatusMatching.NAO_ENCONTRADO
        )
        estatisticas = {
            "restaurantes_extraidos": total_extraidos,
            "restaurantes_salvos": len(items_finais),
            "descartados_separador": descartados_separador,
            "sinalizados_baixa_confianca": sinalizados_baixa_confianca,
            "sinalizados_ruido": sinalizados_ruido,
            "nao_encontrados_google": nao_encontrados_google,
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
            "is_ranking": is_ranking,
            "quantidade_esperada": extracted.quantidade_esperada,
        }
        logger.info(
            "guias_ai.job.funil_final job_id=%s extraidos=%s salvos=%s separador=%s "
            "ruido=%s baixa_confianca=%s matches_internos=%s enriquecidos_google=%s "
            "nao_encontrados_google=%s pendencias=%s is_ranking=%s",
            job_id,
            total_extraidos,
            len(items_finais),
            descartados_separador,
            sinalizados_ruido,
            sinalizados_baixa_confianca,
            matches_internos,
            estatisticas["enriquecidos_google"],
            nao_encontrados_google,
            pendencias,
            is_ranking,
        )

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
            nao_encontrados_google=nao_encontrados_google,
            is_ranking=is_ranking,
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
        nao_encontrados_google_resumir = sum(
            1
            for item in items_finais
            if item.status_matching == StatusMatching.NAO_ENCONTRADO
        )
        is_ranking_resumir = bool(
            (guia.get("metadados") or {}).get("is_ranking")
            if isinstance(guia.get("metadados"), dict)
            else False
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
            nao_encontrados_google=nao_encontrados_google_resumir,
            is_ranking=is_ranking_resumir,
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
        is_ranking: bool = False,
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
                "tipo_guia_detectado": extracted.tipo_guia_detectado,
                "is_ranking": is_ranking,
                "ordem_origem": "ranking" if is_ranking else "texto_original",
                "quantidade_esperada": extracted.quantidade_esperada,
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

    async def _persistir_itens_finais(
        self,
        *,
        job_id: str,
        guia_id: str,
        item_ids: dict[int, str],
        items_finais: list[EnrichedItem],
        initial_items_insert_attempted: bool,
        alertas: list[str],
    ) -> dict[int, str]:
        if len(item_ids) < len(items_finais):
            recovered = await self._carregar_item_ids_por_ordem(guia_id=guia_id)
            if recovered:
                item_ids = {**recovered, **item_ids}
                logger.info(
                    "guias_ai.job.final_item_ids_recovered job_id=%s guia_id=%s recovered=%s coverage=%s/%s",
                    job_id,
                    guia_id,
                    len(recovered),
                    len(item_ids),
                    len(items_finais),
                )
                for index, item in enumerate(items_finais):
                    await self._patch_item_enriquecido(
                        item_id=item_ids.get(index),
                        item=item,
                    )

        if not item_ids:
            if initial_items_insert_attempted:
                logger.error(
                    "guias_ai.job.skip_full_bulk_insert_without_item_ids job_id=%s guia_id=%s total=%s reason=initial_insert_attempted",
                    job_id,
                    guia_id,
                    len(items_finais),
                )
                alertas.append("itens_iniciais_sem_ids_para_patch")
                return item_ids

            itens_payload = [
                self._build_item_payload(guia_id=guia_id, ordem=index, item=item)
                for index, item in enumerate(items_finais)
            ]
            try:
                await self._supabase.insert_guia_itens(items=itens_payload)
                logger.info(
                    "guias_ai.job.final_bulk_inserted job_id=%s guia_id=%s total=%s",
                    job_id,
                    guia_id,
                    len(itens_payload),
                )
            except ExternalServiceError as exc:
                logger.warning(
                    "guias_ai.job.insert_itens_failed job_id=%s reason=%s",
                    job_id,
                    exc.message,
                )
                alertas.append("falha_ao_persistir_itens")
            return item_ids

        missing_indexes = [
            index for index in range(len(items_finais)) if index not in item_ids
        ]
        if not missing_indexes:
            return item_ids

        logger.warning(
            "guias_ai.job.missing_item_ids_before_final_insert job_id=%s guia_id=%s missing=%s sample=%s",
            job_id,
            guia_id,
            len(missing_indexes),
            missing_indexes[:10],
        )
        if initial_items_insert_attempted:
            alertas.append("alguns_itens_sem_ids_para_patch")
            logger.error(
                "guias_ai.job.skip_missing_bulk_insert_after_initial_insert job_id=%s guia_id=%s missing=%s",
                job_id,
                guia_id,
                len(missing_indexes),
            )
            return item_ids

        itens_payload = [
            self._build_item_payload(
                guia_id=guia_id,
                ordem=index,
                item=items_finais[index],
            )
            for index in missing_indexes
        ]
        try:
            await self._supabase.insert_guia_itens(items=itens_payload)
            logger.info(
                "guias_ai.job.final_missing_inserted job_id=%s guia_id=%s total=%s sample=%s",
                job_id,
                guia_id,
                len(itens_payload),
                missing_indexes[:10],
            )
        except ExternalServiceError as exc:
            logger.warning(
                "guias_ai.job.insert_missing_itens_failed job_id=%s reason=%s",
                job_id,
                exc.message,
            )
            alertas.append("falha_ao_persistir_itens")
        return item_ids

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
        logger.info(
            "guias_ai.job.initial_items_insert_start guia_id=%s requested=%s sample=%s",
            guia_id,
            len(payload),
            [item["nome_importado"] for item in payload[:5]],
        )
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
            "guias_ai.job.initial_items_insert_response guia_id=%s requested=%s returned=%s ids=%s",
            guia_id,
            len(candidatos),
            len(inseridos),
            len(ids),
        )
        if len(ids) < len(candidatos):
            recovered = await self._carregar_item_ids_por_ordem(guia_id=guia_id)
            if recovered:
                ids = {**recovered, **ids}
                logger.info(
                    "guias_ai.job.initial_item_ids_recovered guia_id=%s recovered=%s coverage=%s/%s",
                    guia_id,
                    len(recovered),
                    len(ids),
                    len(candidatos),
                )
            else:
                logger.warning(
                    "guias_ai.job.initial_item_ids_missing guia_id=%s requested=%s returned=%s ids=%s",
                    guia_id,
                    len(candidatos),
                    len(inseridos),
                    len(ids),
                )
        logger.info(
            "guias_ai.job.initial_items_inserted guia_id=%s total=%s",
            guia_id,
            len(ids),
        )
        return ids

    async def _carregar_item_ids_por_ordem(self, *, guia_id: str) -> dict[int, str]:
        try:
            rows = await self._supabase.list_guia_itens(guia_id=guia_id)
        except ExternalServiceError as exc:
            logger.warning(
                "guias_ai.job.load_item_ids_failed guia_id=%s reason=%s",
                guia_id,
                exc.message,
            )
            return {}
        except Exception:
            logger.exception("guias_ai.job.load_item_ids_unexpected guia_id=%s", guia_id)
            return {}

        ids: dict[int, str] = {}
        duplicates = 0
        without_order = 0
        for row in rows:
            if not isinstance(row, dict) or not row.get("id"):
                continue
            ordem = _int_or_none(row.get("ordem"))
            if ordem is None:
                without_order += 1
                continue
            if ordem in ids:
                duplicates += 1
                continue
            ids[ordem] = str(row["id"])
        logger.info(
            "guias_ai.job.item_ids_loaded guia_id=%s rows=%s ids=%s duplicates=%s without_order=%s",
            guia_id,
            len(rows),
            len(ids),
            duplicates,
            without_order,
        )
        if duplicates:
            logger.warning(
                "guias_ai.job.duplicate_item_orders guia_id=%s duplicates=%s",
                guia_id,
                duplicates,
            )
        return ids

    async def _patch_item_enriquecido(
        self,
        *,
        item_id: str | None,
        item: EnrichedItem,
    ) -> None:
        if not item_id:
            logger.warning(
                "guias_ai.job.patch_item_skipped_missing_id ordem=%s nome=%s status=%s has_photo=%s has_maps=%s",
                item.extracted.ordem,
                item.extracted.nome_original[:80],
                item.status_matching.value,
                bool(item.foto_url),
                bool(item.google_maps_uri),
            )
            return
        payload = self._build_item_update_payload(item)
        try:
            await self._supabase.update_guia_item(item_id=item_id, payload=payload)
            logger.info(
                "guias_ai.job.patch_item_ok item_id=%s ordem=%s nome=%s status=%s has_photo=%s has_maps=%s lugar_id=%s",
                item_id,
                item.extracted.ordem,
                item.extracted.nome_original[:80],
                item.status_matching.value,
                bool(item.foto_url),
                bool(item.google_maps_uri),
                bool(item.lugar_id),
            )
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
        internal_lugar, internal_score, internal_status = match
        if internal_status == StatusMatching.ENCONTRADO_INTERNO and internal_lugar:
            return JobRunner._merge_internal_match(
                enriched=enriched,
                internal_lugar=internal_lugar,
                internal_score=internal_score,
                status=StatusMatching.ENCONTRADO_INTERNO,
            )

        if internal_status == StatusMatching.POSSIVEL_DUPLICADO and internal_lugar:
            enriched = JobRunner._merge_internal_match(
                enriched=enriched,
                internal_lugar=internal_lugar,
                internal_score=internal_score,
                status=enriched.status_matching,
            )
            if enriched.status_matching not in (
                StatusMatching.NAO_ENCONTRADO,
                StatusMatching.IGNORADO,
            ):
                enriched.status_matching = StatusMatching.POSSIVEL_DUPLICADO
                if "possivel_duplicado_interno" not in enriched.alertas:
                    enriched.alertas.append("possivel_duplicado_interno")
        return enriched

    @staticmethod
    def _build_internal_enriched_item(
        *,
        restaurant: ExtractedRestaurant,
        internal_lugar: dict[str, Any],
        internal_score: float,
    ) -> EnrichedItem:
        extra = internal_lugar.get("extra") if isinstance(internal_lugar.get("extra"), dict) else {}
        maps_uri, site = _split_maps_and_site(
            link=_string_or_none(internal_lugar.get("link")),
            extra=extra,
        )
        categories = _string_list(
            extra.get("categorias_google")
            or extra.get("types")
            or extra.get("categorias")
        )
        primary_type = _string_or_none(extra.get("primary_type"))
        if primary_type and primary_type not in categories:
            categories.insert(0, primary_type)

        return EnrichedItem(
            extracted=restaurant,
            place_id=_string_or_none(internal_lugar.get("place_id")),
            nome_oficial=_string_or_none(internal_lugar.get("nome")),
            endereco=_first_string(
                extra.get("formatted_address"),
                extra.get("endereco"),
                extra.get("address"),
            ),
            latitude=_float_or_none(extra.get("latitude")),
            longitude=_float_or_none(extra.get("longitude")),
            google_maps_uri=maps_uri,
            telefone=_first_string(extra.get("telefone"), extra.get("phone_number")),
            site=site,
            rating=_float_or_none(extra.get("rating")),
            total_avaliacoes=_int_or_none(
                extra.get("total_avaliacoes")
                or extra.get("user_rating_count")
                or extra.get("userRatingCount")
            ),
            preco_nivel=_int_or_none(
                internal_lugar.get("faixa_preco")
                or extra.get("preco_nivel")
                or extra.get("price_range")
            ),
            foto_url=_internal_cover_url(internal_lugar),
            status_negocio=_first_string(extra.get("status_negocio"), extra.get("business_status")),
            aberto_agora=_bool_or_none(extra.get("aberto_agora"), extra.get("open_now")),
            bairro_normalizado=_string_or_none(internal_lugar.get("bairro")),
            cidade_normalizada=_string_or_none(internal_lugar.get("cidade")),
            categorias_google=categories,
            confianca_enriquecimento=internal_score,
            status_matching=StatusMatching.ENCONTRADO_INTERNO,
            score_matching=internal_score,
            lugar_id=_string_or_none(internal_lugar.get("id")),
            lugar_existente=internal_lugar,
        )

    @staticmethod
    def _merge_internal_match(
        *,
        enriched: EnrichedItem,
        internal_lugar: dict[str, Any],
        internal_score: float,
        status: StatusMatching,
    ) -> EnrichedItem:
        internal = JobRunner._build_internal_enriched_item(
            restaurant=enriched.extracted,
            internal_lugar=internal_lugar,
            internal_score=internal_score,
        )

        merged = enriched.model_copy(deep=True)
        for field in (
            "place_id",
            "nome_oficial",
            "endereco",
            "latitude",
            "longitude",
            "google_maps_uri",
            "telefone",
            "site",
            "rating",
            "total_avaliacoes",
            "preco_nivel",
            "foto_url",
            "foto_atribuicao",
            "status_negocio",
            "aberto_agora",
            "bairro_normalizado",
            "cidade_normalizada",
        ):
            if getattr(merged, field) in (None, "", []):
                setattr(merged, field, getattr(internal, field))

        if not merged.categorias_google:
            merged.categorias_google = internal.categorias_google
        merged.lugar_id = internal.lugar_id
        merged.lugar_existente = internal_lugar
        merged.status_matching = status
        merged.score_matching = max(float(merged.score_matching or 0.0), internal_score)
        merged.confianca_enriquecimento = max(
            float(merged.confianca_enriquecimento or 0.0),
            internal_score,
        )
        merged.alertas = list(dict.fromkeys([*internal.alertas, *merged.alertas]))
        return merged

    @staticmethod
    def _needs_google_hydration(item: EnrichedItem | None) -> bool:
        if item is None or item.status_matching != StatusMatching.ENCONTRADO_INTERNO:
            return False
        return not item.foto_url or not item.google_maps_uri

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
        nao_encontrados_google: int = 0,
        is_ranking: bool = False,
    ) -> str:
        if total == 0:
            return "Nao consegui identificar restaurantes neste texto."

        if is_ranking:
            partes = [f"Seu guia foi criado com {total} restaurantes na ordem do ranking."]
        else:
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
        if nao_encontrados_google:
            partes.append(
                f"{nao_encontrados_google} {'ficou' if nao_encontrados_google == 1 else 'ficaram'} "
                "so com o nome (nao achamos no Google Maps) e voce pode revisar depois."
            )
        if pendencias and pendencias != nao_encontrados_google:
            outros_pendentes = pendencias - nao_encontrados_google
            if outros_pendentes > 0:
                partes.append(
                    f"{outros_pendentes} {'precisa' if outros_pendentes == 1 else 'precisam'} de revisao."
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


def _split_maps_and_site(
    *,
    link: str | None,
    extra: dict[str, Any],
) -> tuple[str | None, str | None]:
    maps_uri = _first_string(
        extra.get("google_maps_uri"),
        extra.get("googleMapsUri"),
        extra.get("maps_uri"),
    )
    site = _first_string(extra.get("website_uri"), extra.get("site"), extra.get("website"))

    if link:
        if _is_google_maps_url(link):
            maps_uri = maps_uri or link
        else:
            site = site or link

    return maps_uri, site


def _is_google_maps_url(value: str) -> bool:
    lower = value.lower()
    return (
        "google.com/maps" in lower
        or "maps.google." in lower
        or "maps.app.goo.gl" in lower
        or "goo.gl/maps" in lower
    )


def _internal_cover_url(internal_lugar: dict[str, Any]) -> str | None:
    cover = _string_or_none(internal_lugar.get("imagem_capa"))
    if cover:
        return cover

    fotos = internal_lugar.get("fotos")
    if not isinstance(fotos, list):
        return None

    candidates = [item for item in fotos if isinstance(item, dict)]
    candidates.sort(
        key=lambda item: (
            not bool(item.get("capa")),
            _int_or_none(item.get("ordem")) or 0,
        )
    )
    for item in candidates:
        url = _first_string(item.get("url"), item.get("public_url"), item.get("photo_uri"))
        if url:
            return url
    return None


def _first_string(*values: Any) -> str | None:
    for value in values:
        cleaned = _string_or_none(value)
        if cleaned:
            return cleaned
    return None


def _string_or_none(value: Any) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value.strip()))
        except ValueError:
            return None
    return None


def _bool_or_none(*values: Any) -> bool | None:
    for value in values:
        if isinstance(value, bool):
            return value
    return None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]

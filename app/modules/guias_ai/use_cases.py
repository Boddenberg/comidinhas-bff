from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from app.core.config import Settings
from app.core.errors import BadRequestError, ConfigurationError, NotFoundError
from app.integrations.google_places.client import GooglePlacesClient
from app.integrations.openai.client import OpenAIClient
from app.integrations.supabase.client import SupabaseClient
from app.modules.guias_ai.job_runner import JobRunner
from app.modules.guias_ai.sanitizer import hash_texto, normalizar_texto
from app.modules.guias_ai.schemas import (
    CriarGuiaIaRequest,
    GuiaIaCapaUpdateRequest,
    GuiaIaItemResponse,
    GuiaIaItemUpdateRequest,
    GuiaIaItensReorderRequest,
    GuiaIaMetadataUpdateRequest,
    GuiaIaResponse,
    GuiaIaSugestoes,
    JobResponse,
    JOB_PROGRESS,
    JOB_USER_LABEL,
    JobResumoEstatisticas,
    JobStatus,
    StatusMatching,
)

logger = logging.getLogger(__name__)


class GuiasAiUseCase:
    """High level orchestrator for the "Criar guia com IA" feature.

    The HTTP handler stays thin: it asks the use case to create a job, the use
    case schedules background processing and returns immediately. Subsequent
    polling endpoints read state from the persisted job.
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
        self._runner = JobRunner(
            settings=settings,
            supabase_client=supabase_client,
            openai_client=openai_client,
            google_places_client=google_places_client,
        )

    async def criar_job(self, *, request: CriarGuiaIaRequest) -> JobResponse:
        if not self._settings.guias_ai_enabled:
            raise ConfigurationError("A funcionalidade de criacao de guia com IA esta desativada.")
        if not self._settings.is_openai_configured:
            raise ConfigurationError(
                "Configure OPENAI_API_KEY para usar a criacao de guia com IA.",
            )
        await self._garantir_grupo(grupo_id=request.grupo_id)

        texto_limpo = normalizar_texto(request.texto)
        if len(texto_limpo) < self._settings.guias_ai_text_min_chars:
            raise BadRequestError(
                "O texto colado e curto demais para gerar um guia.",
            )
        if len(texto_limpo) > self._settings.guias_ai_text_max_chars * 2:
            raise BadRequestError(
                "O texto colado ultrapassa o limite maximo permitido."
            )

        texto_hash_value = hash_texto(texto_limpo[: self._settings.guias_ai_text_max_chars])
        existente = await self._supabase.get_guia_ai_job_by_hash(
            grupo_id=request.grupo_id,
            texto_hash=texto_hash_value,
        )

        payload: dict[str, Any] = {
            "grupo_id": request.grupo_id,
            "perfil_id": request.perfil_id,
            "status": JobStatus.CREATED.value,
            "etapa_atual": JOB_USER_LABEL[JobStatus.CREATED],
            "progresso_percentual": JOB_PROGRESS[JobStatus.CREATED],
            "texto_original": texto_limpo,
            "texto_hash": texto_hash_value,
            "url_origem": request.url_origem,
            "resultado": (
                {"titulo_sugerido": request.titulo_sugerido}
                if request.titulo_sugerido
                else {}
            ),
            "mensagem_usuario": "Recebemos seu texto e estamos comecando a processar.",
        }
        if existente and existente.get("guia_id"):
            payload["resultado"] = {
                **payload.get("resultado", {}),
                "duplicado_de_job_id": existente.get("id"),
                "guia_anterior_id": existente.get("guia_id"),
            }

        criado = await self._supabase.insert_guia_ai_job(payload=payload)
        job_id = str(criado.get("id", ""))
        logger.info(
            "guias_ai.job.created job_id=%s grupo_id=%s perfil_id=%s tamanho=%s",
            job_id,
            request.grupo_id,
            request.perfil_id,
            len(texto_limpo),
        )

        # Background processing — does not block the HTTP request.
        task = asyncio.create_task(
            self._runner.executar(job_id=job_id),
            name=f"guias_ai_job:{job_id}",
        )
        task.add_done_callback(self._log_task_outcome)
        return self._mapear_job(criado)

    async def status_job(self, *, job_id: str) -> JobResponse:
        raw = await self._supabase.get_guia_ai_job(job_id=job_id)
        if raw is None:
            raise NotFoundError("Job de importacao nao encontrado.")
        return self._mapear_job(raw)

    async def listar_jobs(
        self,
        *,
        grupo_id: str,
        limit: int = 20,
    ) -> list[JobResponse]:
        await self._garantir_grupo(grupo_id=grupo_id)
        rows = await self._supabase.list_guia_ai_jobs(grupo_id=grupo_id, limit=limit)
        return [self._mapear_job(row) for row in rows]

    async def buscar_guia_ia(self, *, guia_id: str) -> GuiaIaResponse:
        guia = await self._supabase.get_guia(guia_id=guia_id)
        if guia is None:
            raise NotFoundError("Guia nao encontrado.")
        itens = await self._supabase.list_guia_itens(guia_id=guia_id)
        return self._mapear_guia(guia, itens)

    async def atualizar_metadados(
        self,
        *,
        guia_id: str,
        request: GuiaIaMetadataUpdateRequest,
    ) -> GuiaIaResponse:
        guia = await self._supabase.get_guia(guia_id=guia_id)
        if guia is None:
            raise NotFoundError("Guia nao encontrado.")

        payload: dict[str, Any] = {}
        if "nome" in request.model_fields_set and request.nome is not None:
            payload["nome"] = request.nome
        if "descricao" in request.model_fields_set:
            payload["descricao"] = request.descricao
        if "categoria" in request.model_fields_set:
            payload["categoria"] = request.categoria
        if "regiao" in request.model_fields_set:
            payload["regiao"] = request.regiao
        if "cidade_principal" in request.model_fields_set:
            payload["cidade_principal"] = request.cidade_principal

        if not payload:
            raise BadRequestError("Informe ao menos um campo para atualizar.")

        await self._supabase.update_guia(guia_id=guia_id, payload=payload)
        return await self.buscar_guia_ia(guia_id=guia_id)

    async def atualizar_capa(
        self,
        *,
        guia_id: str,
        request: GuiaIaCapaUpdateRequest,
    ) -> GuiaIaResponse:
        guia = await self._supabase.get_guia(guia_id=guia_id)
        if guia is None:
            raise NotFoundError("Guia nao encontrado.")

        if "imagem_capa" not in request.model_fields_set and request.item_id is None:
            raise BadRequestError("Informe imagem_capa ou item_id.")

        nova_capa = request.imagem_capa
        if request.item_id:
            item = await self._supabase.get_guia_item(item_id=request.item_id)
            if item is None or str(item.get("guia_id")) != guia_id:
                raise NotFoundError("Item de guia nao encontrado.")
            foto_item = item.get("foto_url")
            if not isinstance(foto_item, str) or not foto_item.strip():
                raise BadRequestError("O item selecionado nao tem foto disponivel.")
            nova_capa = foto_item

        await self._supabase.update_guia(
            guia_id=guia_id,
            payload={"imagem_capa": nova_capa},
        )
        return await self.buscar_guia_ia(guia_id=guia_id)

    async def remover_item(self, *, guia_id: str, item_id: str) -> GuiaIaResponse:
        item = await self._supabase.get_guia_item(item_id=item_id)
        if item is None or str(item.get("guia_id")) != guia_id:
            raise NotFoundError("Item de guia nao encontrado.")
        await self._supabase.delete_guia_item(item_id=item_id)
        await self._sincronizar_total_e_lugar_ids(guia_id=guia_id)
        return await self.buscar_guia_ia(guia_id=guia_id)

    async def reordenar_itens(
        self,
        *,
        guia_id: str,
        request: GuiaIaItensReorderRequest,
    ) -> GuiaIaResponse:
        itens = await self._supabase.list_guia_itens(guia_id=guia_id)
        ids_atuais = {str(i.get("id")) for i in itens if isinstance(i, dict)}
        if set(request.item_ids) != ids_atuais:
            raise BadRequestError(
                "Envie todos os itens do guia, exatamente uma vez cada, na nova ordem.",
            )
        for ordem, item_id in enumerate(request.item_ids):
            await self._supabase.update_guia_item(
                item_id=item_id,
                payload={"ordem": ordem},
            )
        await self._sincronizar_total_e_lugar_ids(guia_id=guia_id)
        return await self.buscar_guia_ia(guia_id=guia_id)

    async def atualizar_item(
        self,
        *,
        guia_id: str,
        item_id: str,
        request: GuiaIaItemUpdateRequest,
    ) -> GuiaIaItemResponse:
        item = await self._supabase.get_guia_item(item_id=item_id)
        if item is None or str(item.get("guia_id")) != guia_id:
            raise NotFoundError("Item de guia nao encontrado.")

        payload: dict[str, Any] = {}
        if "nome_importado" in request.model_fields_set and request.nome_importado:
            payload["nome_importado"] = request.nome_importado
        if "bairro" in request.model_fields_set:
            payload["bairro"] = request.bairro
        if "cidade" in request.model_fields_set:
            payload["cidade"] = request.cidade
        if "categoria" in request.model_fields_set:
            payload["categoria"] = request.categoria
        if "foto_url" in request.model_fields_set:
            payload["foto_url"] = request.foto_url

        if request.desassociar_lugar:
            payload["lugar_id"] = None
            payload["status_matching"] = StatusMatching.PENDENTE.value
        elif request.lugar_id is not None:
            lugar = await self._supabase.get_lugar(
                lugar_id=request.lugar_id,
                select="id,grupo_id",
            )
            if lugar is None:
                raise NotFoundError("Lugar nao encontrado para associar ao item.")
            guia = await self._supabase.get_guia(guia_id=guia_id)
            if guia and str(lugar.get("grupo_id")) != str(guia.get("grupo_id")):
                raise BadRequestError(
                    "O lugar precisa pertencer ao mesmo grupo do guia."
                )
            payload["lugar_id"] = request.lugar_id
            payload["status_matching"] = StatusMatching.CONFIRMADO_USUARIO.value

        if request.status_matching is not None:
            payload["status_matching"] = request.status_matching.value
        if request.confirmar:
            payload["status_matching"] = StatusMatching.CONFIRMADO_USUARIO.value

        if not payload:
            raise BadRequestError("Informe ao menos um campo para atualizar.")

        await self._supabase.update_guia_item(item_id=item_id, payload=payload)
        await self._sincronizar_total_e_lugar_ids(guia_id=guia_id)
        atualizado = await self._supabase.get_guia_item(item_id=item_id)
        if atualizado is None:
            raise NotFoundError("Item desapareceu apos a atualizacao.")
        return self._mapear_item(atualizado)

    async def _sincronizar_total_e_lugar_ids(self, *, guia_id: str) -> None:
        itens = await self._supabase.list_guia_itens(guia_id=guia_id)
        lugar_ids: list[str] = []
        seen: set[str] = set()
        for item in itens:
            lugar_id = item.get("lugar_id") if isinstance(item, dict) else None
            if isinstance(lugar_id, str) and lugar_id and lugar_id not in seen:
                seen.add(lugar_id)
                lugar_ids.append(lugar_id)
        await self._supabase.update_guia(
            guia_id=guia_id,
            payload={
                "total_itens": len(itens),
                "lugar_ids": lugar_ids,
            },
        )

    async def _garantir_grupo(self, *, grupo_id: str) -> None:
        grupo = await self._supabase.get_grupo(grupo_id=grupo_id)
        if grupo is None:
            raise NotFoundError("Grupo nao encontrado.")

    @staticmethod
    def _log_task_outcome(task: asyncio.Task[Any]) -> None:
        if task.cancelled():
            logger.warning("guias_ai.job.task_cancelled name=%s", task.get_name())
            return
        exc = task.exception()
        if exc is not None:
            logger.error(
                "guias_ai.job.task_error name=%s error=%s",
                task.get_name(),
                exc,
            )

    @staticmethod
    def _mapear_job(raw: dict[str, Any]) -> JobResponse:
        try:
            status = JobStatus(str(raw.get("status") or JobStatus.CREATED.value))
        except ValueError:
            status = JobStatus.CREATED

        etapas = raw.get("etapas_concluidas")
        if not isinstance(etapas, list):
            etapas = []

        estatisticas_raw = raw.get("estatisticas") or {}
        if not isinstance(estatisticas_raw, dict):
            estatisticas_raw = {}

        alertas_raw = raw.get("alertas")
        alertas = [a for a in alertas_raw if isinstance(a, str)] if isinstance(alertas_raw, list) else []

        return JobResponse(
            id=str(raw.get("id", "")),
            grupo_id=str(raw.get("grupo_id", "")),
            perfil_id=raw.get("perfil_id"),
            guia_id=raw.get("guia_id"),
            status=status,
            etapa_atual=raw.get("etapa_atual"),
            etapas_concluidas=[str(e) for e in etapas if isinstance(e, str)],
            progresso_percentual=int(raw.get("progresso_percentual") or 0),
            progresso_label=JOB_USER_LABEL.get(status, status.value),
            mensagem_usuario=raw.get("mensagem_usuario"),
            motivo_invalido=raw.get("motivo_invalido"),
            alertas=alertas,
            estatisticas=JobResumoEstatisticas(**{
                k: v
                for k, v in estatisticas_raw.items()
                if k in JobResumoEstatisticas.model_fields
            }),
            iniciado_em=_parse_dt(raw.get("iniciado_em")),
            concluido_em=_parse_dt(raw.get("concluido_em")),
            criado_em=_parse_dt(raw.get("criado_em")),
            atualizado_em=_parse_dt(raw.get("atualizado_em")),
        )

    def _mapear_guia(
        self,
        guia: dict[str, Any],
        itens: list[dict[str, Any]],
    ) -> GuiaIaResponse:
        sugestoes_raw = guia.get("sugestoes") or {}
        sugestoes = (
            GuiaIaSugestoes(**sugestoes_raw)
            if isinstance(sugestoes_raw, dict)
            else GuiaIaSugestoes()
        )

        alertas_raw = guia.get("alertas") or []
        alertas = (
            [a for a in alertas_raw if isinstance(a, str)]
            if isinstance(alertas_raw, list)
            else []
        )
        metadados_raw = guia.get("metadados") or {}

        return GuiaIaResponse(
            id=str(guia.get("id", "")),
            grupo_id=str(guia.get("grupo_id", "")),
            nome=str(guia.get("nome", "")),
            descricao=guia.get("descricao"),
            tipo_guia=str(guia.get("tipo_guia") or "manual"),
            fonte=guia.get("fonte"),
            autor=guia.get("autor"),
            url_origem=guia.get("url_origem"),
            data_publicacao=_parse_dt(guia.get("data_publicacao")),
            categoria=guia.get("categoria"),
            regiao=guia.get("regiao"),
            cidade_principal=guia.get("cidade_principal"),
            imagem_capa=guia.get("imagem_capa"),
            total_itens=int(guia.get("total_itens") or len(itens)),
            status_importacao=guia.get("status_importacao"),
            qualidade_importacao=guia.get("qualidade_importacao"),
            alertas=alertas,
            metadados=metadados_raw if isinstance(metadados_raw, dict) else {},
            sugestoes=sugestoes,
            itens=[self._mapear_item(item) for item in itens],
            criado_em=_parse_dt(guia.get("criado_em")),
            atualizado_em=_parse_dt(guia.get("atualizado_em")),
        )

    @staticmethod
    def _mapear_item(item: dict[str, Any]) -> GuiaIaItemResponse:
        try:
            status = StatusMatching(str(item.get("status_matching") or "pendente"))
        except ValueError:
            status = StatusMatching.PENDENTE

        horarios_raw = item.get("horarios")
        horarios = [h for h in horarios_raw if isinstance(h, str)] if isinstance(horarios_raw, list) else []
        alertas_raw = item.get("alertas")
        alertas = [a for a in alertas_raw if isinstance(a, str)] if isinstance(alertas_raw, list) else []

        extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}

        return GuiaIaItemResponse(
            id=str(item.get("id", "")),
            posicao_ranking=item.get("posicao_ranking"),
            ordem=int(item.get("ordem") or 0),
            nome_importado=str(item.get("nome_importado", "")),
            nome_normalizado=item.get("nome_normalizado"),
            bairro=item.get("bairro"),
            cidade=item.get("cidade"),
            estado=item.get("estado"),
            categoria=item.get("categoria"),
            place_id=item.get("place_id"),
            endereco=item.get("endereco"),
            latitude=item.get("latitude"),
            longitude=item.get("longitude"),
            google_maps_uri=item.get("google_maps_uri"),
            telefone=item.get("telefone"),
            site=item.get("site"),
            rating=item.get("rating"),
            total_avaliacoes=item.get("total_avaliacoes"),
            preco_nivel=item.get("preco_nivel"),
            foto_url=item.get("foto_url"),
            foto_atribuicao=item.get("foto_atribuicao"),
            status_negocio=item.get("status_negocio"),
            horarios=horarios,
            status_matching=status,
            score_matching=item.get("score_matching"),
            confianca_extracao=item.get("confianca_extracao"),
            confianca_enriquecimento=item.get("confianca_enriquecimento"),
            alertas=alertas,
            trecho_original=item.get("trecho_original"),
            lugar_id=item.get("lugar_id"),
            extra=extra,
        )


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None

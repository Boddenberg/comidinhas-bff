from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query

from app.api.dependencies import get_guias_ai_use_case
from app.modules.guias_ai.schemas import (
    CriarGuiaIaRequest,
    GuiaIaCapaUpdateRequest,
    GuiaIaItemResponse,
    GuiaIaItemUpdateRequest,
    GuiaIaItensReorderRequest,
    GuiaIaMetadataUpdateRequest,
    GuiaIaResponse,
    JobResponse,
)
from app.modules.guias_ai.use_cases import GuiasAiUseCase

router = APIRouter(prefix="/guias/ia", tags=["guias-ia"])


@router.post(
    "/imports",
    response_model=JobResponse,
    status_code=202,
    summary="Cria um job para gerar um guia gastronomico a partir de texto",
)
async def criar_import(
    request: CriarGuiaIaRequest,
    use_case: GuiasAiUseCase = Depends(get_guias_ai_use_case),
) -> JobResponse:
    return await use_case.criar_job(request=request)


@router.get(
    "/imports/{job_id}",
    response_model=JobResponse,
    summary="Consulta o status de um job de importacao por IA",
)
async def status_import(
    job_id: str = Path(..., min_length=8, max_length=64),
    use_case: GuiasAiUseCase = Depends(get_guias_ai_use_case),
) -> JobResponse:
    return await use_case.status_job(job_id=job_id)


@router.get(
    "/imports",
    response_model=list[JobResponse],
    summary="Lista os ultimos jobs de importacao do grupo",
)
async def listar_imports(
    grupo_id: str = Query(..., min_length=8, max_length=64),
    limit: int = Query(default=20, ge=1, le=100),
    use_case: GuiasAiUseCase = Depends(get_guias_ai_use_case),
) -> list[JobResponse]:
    return await use_case.listar_jobs(grupo_id=grupo_id, limit=limit)


@router.post(
    "/imports/{job_id}/cancelar",
    response_model=JobResponse,
    summary="Cancela um job de importacao em andamento",
)
async def cancelar_import(
    job_id: str = Path(..., min_length=8, max_length=64),
    use_case: GuiasAiUseCase = Depends(get_guias_ai_use_case),
) -> JobResponse:
    return await use_case.cancelar_job(job_id=job_id)


@router.post(
    "/imports/{job_id}/reexecutar",
    response_model=JobResponse,
    status_code=202,
    summary="Reexecuta um job que falhou, foi cancelado ou marcado como invalido",
)
async def reexecutar_import(
    job_id: str = Path(..., min_length=8, max_length=64),
    use_case: GuiasAiUseCase = Depends(get_guias_ai_use_case),
) -> JobResponse:
    return await use_case.reexecutar_job(job_id=job_id)


@router.post(
    "/imports/watchdog",
    summary="Marca como 'failed' jobs que ficaram travados sem atualizacao",
)
async def executar_watchdog(
    use_case: GuiasAiUseCase = Depends(get_guias_ai_use_case),
) -> dict:
    return await use_case.watchdog()


@router.get(
    "/{guia_id}",
    response_model=GuiaIaResponse,
    summary="Retorna o guia criado por IA com itens, sugestoes e metadados",
)
async def buscar_guia_ia(
    guia_id: str = Path(..., min_length=8, max_length=64),
    use_case: GuiasAiUseCase = Depends(get_guias_ai_use_case),
) -> GuiaIaResponse:
    return await use_case.buscar_guia_ia(guia_id=guia_id)


@router.patch(
    "/{guia_id}",
    response_model=GuiaIaResponse,
    summary="Atualiza nome, descricao e metadados do guia",
)
async def atualizar_metadados(
    request: GuiaIaMetadataUpdateRequest,
    guia_id: str = Path(..., min_length=8, max_length=64),
    use_case: GuiasAiUseCase = Depends(get_guias_ai_use_case),
) -> GuiaIaResponse:
    return await use_case.atualizar_metadados(guia_id=guia_id, request=request)


@router.patch(
    "/{guia_id}/capa",
    response_model=GuiaIaResponse,
    summary="Atualiza a foto de capa do guia",
)
async def atualizar_capa(
    request: GuiaIaCapaUpdateRequest,
    guia_id: str = Path(..., min_length=8, max_length=64),
    use_case: GuiasAiUseCase = Depends(get_guias_ai_use_case),
) -> GuiaIaResponse:
    return await use_case.atualizar_capa(guia_id=guia_id, request=request)


@router.patch(
    "/{guia_id}/itens/reordenar",
    response_model=GuiaIaResponse,
    summary="Reordena os itens do guia",
)
async def reordenar_itens(
    request: GuiaIaItensReorderRequest,
    guia_id: str = Path(..., min_length=8, max_length=64),
    use_case: GuiasAiUseCase = Depends(get_guias_ai_use_case),
) -> GuiaIaResponse:
    return await use_case.reordenar_itens(guia_id=guia_id, request=request)


@router.patch(
    "/{guia_id}/itens/{item_id}",
    response_model=GuiaIaItemResponse,
    summary="Edita um item do guia (associar lugar, status, foto, etc.)",
)
async def atualizar_item(
    request: GuiaIaItemUpdateRequest,
    guia_id: str = Path(..., min_length=8, max_length=64),
    item_id: str = Path(..., min_length=8, max_length=64),
    use_case: GuiasAiUseCase = Depends(get_guias_ai_use_case),
) -> GuiaIaItemResponse:
    return await use_case.atualizar_item(
        guia_id=guia_id,
        item_id=item_id,
        request=request,
    )


@router.delete(
    "/{guia_id}/itens/{item_id}",
    response_model=GuiaIaResponse,
    summary="Remove um item do guia",
)
async def remover_item(
    guia_id: str = Path(..., min_length=8, max_length=64),
    item_id: str = Path(..., min_length=8, max_length=64),
    use_case: GuiasAiUseCase = Depends(get_guias_ai_use_case),
) -> GuiaIaResponse:
    return await use_case.remover_item(guia_id=guia_id, item_id=item_id)

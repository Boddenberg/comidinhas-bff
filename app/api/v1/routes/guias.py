from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query

from app.api.dependencies import get_manage_guias_use_case
from app.modules.guias.schemas import (
    GuiaCreateRequest,
    GuiaListResponse,
    GuiaLugarRequest,
    GuiaReordenarLugaresRequest,
    GuiaResponse,
    GuiaUpdateRequest,
)
from app.modules.guias.use_cases import ManageGuiasUseCase

router = APIRouter(prefix="/guias", tags=["guias"])


@router.get("/", response_model=GuiaListResponse, summary="Lista guias do grupo selecionado")
async def listar_guias(
    grupo_id: str = Query(..., min_length=8, max_length=64, description="UUID do grupo"),
    use_case: ManageGuiasUseCase = Depends(get_manage_guias_use_case),
) -> GuiaListResponse:
    return await use_case.listar(grupo_id=grupo_id)


@router.post("/", response_model=GuiaResponse, status_code=201, summary="Cria um guia customizado")
async def criar_guia(
    request: GuiaCreateRequest,
    use_case: ManageGuiasUseCase = Depends(get_manage_guias_use_case),
) -> GuiaResponse:
    return await use_case.criar(request=request)


@router.get("/{guia_id}", response_model=GuiaResponse, summary="Busca um guia pelo ID")
async def buscar_guia(
    guia_id: str = Path(..., min_length=8, max_length=64),
    use_case: ManageGuiasUseCase = Depends(get_manage_guias_use_case),
) -> GuiaResponse:
    return await use_case.buscar(guia_id=guia_id)


@router.patch("/{guia_id}", response_model=GuiaResponse, summary="Atualiza nome, descricao ou lugares do guia")
async def atualizar_guia(
    request: GuiaUpdateRequest,
    guia_id: str = Path(..., min_length=8, max_length=64),
    use_case: ManageGuiasUseCase = Depends(get_manage_guias_use_case),
) -> GuiaResponse:
    return await use_case.atualizar(guia_id=guia_id, request=request)


@router.delete("/{guia_id}", summary="Remove o guia")
async def remover_guia(
    guia_id: str = Path(..., min_length=8, max_length=64),
    use_case: ManageGuiasUseCase = Depends(get_manage_guias_use_case),
) -> dict:
    return await use_case.remover(guia_id=guia_id)


@router.post(
    "/{guia_id}/lugares",
    response_model=GuiaResponse,
    status_code=201,
    summary="Adiciona um lugar ao guia",
)
async def adicionar_lugar(
    request: GuiaLugarRequest,
    guia_id: str = Path(..., min_length=8, max_length=64),
    use_case: ManageGuiasUseCase = Depends(get_manage_guias_use_case),
) -> GuiaResponse:
    return await use_case.adicionar_lugar(guia_id=guia_id, request=request)


@router.delete(
    "/{guia_id}/lugares/{lugar_id}",
    response_model=GuiaResponse,
    summary="Remove um lugar do guia",
)
async def remover_lugar(
    guia_id: str = Path(..., min_length=8, max_length=64),
    lugar_id: str = Path(..., min_length=8, max_length=64),
    use_case: ManageGuiasUseCase = Depends(get_manage_guias_use_case),
) -> GuiaResponse:
    return await use_case.remover_lugar(guia_id=guia_id, lugar_id=lugar_id)


@router.patch(
    "/{guia_id}/lugares/reordenar",
    response_model=GuiaResponse,
    summary="Reordena os lugares do guia",
)
async def reordenar_lugares(
    request: GuiaReordenarLugaresRequest,
    guia_id: str = Path(..., min_length=8, max_length=64),
    use_case: ManageGuiasUseCase = Depends(get_manage_guias_use_case),
) -> GuiaResponse:
    return await use_case.reordenar_lugares(guia_id=guia_id, request=request)

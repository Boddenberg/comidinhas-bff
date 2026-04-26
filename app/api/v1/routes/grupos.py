from __future__ import annotations

from fastapi import APIRouter, Depends, Path

from app.api.dependencies import get_manage_grupos_use_case
from app.modules.grupos.schemas import (
    GrupoCreateRequest,
    GrupoListResponse,
    GrupoResponse,
    GrupoUpdateRequest,
)
from app.modules.grupos.use_cases import ManageGruposUseCase

router = APIRouter(prefix="/grupos", tags=["grupos"])


@router.get("/", response_model=GrupoListResponse, summary="Lista todos os grupos")
async def listar_grupos(
    use_case: ManageGruposUseCase = Depends(get_manage_grupos_use_case),
) -> GrupoListResponse:
    return await use_case.listar()


@router.post("/", response_model=GrupoResponse, status_code=201, summary="Cria um novo grupo ou casal")
async def criar_grupo(
    request: GrupoCreateRequest,
    use_case: ManageGruposUseCase = Depends(get_manage_grupos_use_case),
) -> GrupoResponse:
    return await use_case.criar(request=request)


@router.get("/{grupo_id}", response_model=GrupoResponse, summary="Retorna os detalhes de um grupo")
async def buscar_grupo(
    grupo_id: str = Path(..., min_length=8, max_length=64),
    use_case: ManageGruposUseCase = Depends(get_manage_grupos_use_case),
) -> GrupoResponse:
    return await use_case.buscar(grupo_id=grupo_id)


@router.patch("/{grupo_id}", response_model=GrupoResponse, summary="Atualiza nome, tipo, descrição ou membros")
async def atualizar_grupo(
    request: GrupoUpdateRequest,
    grupo_id: str = Path(..., min_length=8, max_length=64),
    use_case: ManageGruposUseCase = Depends(get_manage_grupos_use_case),
) -> GrupoResponse:
    return await use_case.atualizar(grupo_id=grupo_id, request=request)


@router.delete("/{grupo_id}", summary="Remove um grupo e todos os seus lugares")
async def remover_grupo(
    grupo_id: str = Path(..., min_length=8, max_length=64),
    use_case: ManageGruposUseCase = Depends(get_manage_grupos_use_case),
) -> dict:
    return await use_case.remover(grupo_id=grupo_id)

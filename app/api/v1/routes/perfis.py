from __future__ import annotations

from fastapi import APIRouter, Depends, File, Path, Query, UploadFile

from app.api.dependencies import get_manage_perfis_use_case
from app.modules.perfis.schemas import (
    PerfilCreateRequest,
    PerfilListResponse,
    PerfilResponse,
    PerfilUpdateRequest,
)
from app.modules.perfis.use_cases import ManagePerfisUseCase

router = APIRouter(prefix="/perfis", tags=["perfis"])


@router.get("/", response_model=PerfilListResponse, summary="Lista todos os perfis")
async def listar_perfis(
    use_case: ManagePerfisUseCase = Depends(get_manage_perfis_use_case),
) -> PerfilListResponse:
    return await use_case.listar()


@router.post("/", response_model=PerfilResponse, status_code=201, summary="Cria um novo perfil")
async def criar_perfil(
    request: PerfilCreateRequest,
    use_case: ManagePerfisUseCase = Depends(get_manage_perfis_use_case),
) -> PerfilResponse:
    return await use_case.criar(request=request)


@router.get("/por-email", response_model=PerfilResponse, summary="Busca perfil pelo email")
async def buscar_por_email(
    email: str = Query(..., min_length=3, max_length=255),
    use_case: ManagePerfisUseCase = Depends(get_manage_perfis_use_case),
) -> PerfilResponse:
    return await use_case.buscar_por_email(email=email)


@router.get("/{perfil_id}", response_model=PerfilResponse, summary="Busca perfil pelo ID")
async def buscar_perfil(
    perfil_id: str = Path(..., min_length=8, max_length=64),
    use_case: ManagePerfisUseCase = Depends(get_manage_perfis_use_case),
) -> PerfilResponse:
    return await use_case.buscar(perfil_id=perfil_id)


@router.patch("/{perfil_id}", response_model=PerfilResponse, summary="Atualiza nome, email, bio ou cidade")
async def atualizar_perfil(
    request: PerfilUpdateRequest,
    perfil_id: str = Path(..., min_length=8, max_length=64),
    use_case: ManagePerfisUseCase = Depends(get_manage_perfis_use_case),
) -> PerfilResponse:
    return await use_case.atualizar(perfil_id=perfil_id, request=request)


@router.delete("/{perfil_id}", summary="Remove o perfil")
async def remover_perfil(
    perfil_id: str = Path(..., min_length=8, max_length=64),
    use_case: ManagePerfisUseCase = Depends(get_manage_perfis_use_case),
) -> dict:
    return await use_case.remover(perfil_id=perfil_id)


@router.post(
    "/{perfil_id}/foto",
    response_model=PerfilResponse,
    summary="Envia ou substitui a foto do perfil",
)
async def upload_foto(
    file: UploadFile = File(...),
    perfil_id: str = Path(..., min_length=8, max_length=64),
    use_case: ManagePerfisUseCase = Depends(get_manage_perfis_use_case),
) -> PerfilResponse:
    return await use_case.upload_foto(perfil_id=perfil_id, file=file)


@router.delete(
    "/{perfil_id}/foto",
    response_model=PerfilResponse,
    summary="Remove a foto do perfil",
)
async def remover_foto(
    perfil_id: str = Path(..., min_length=8, max_length=64),
    use_case: ManagePerfisUseCase = Depends(get_manage_perfis_use_case),
) -> PerfilResponse:
    return await use_case.remover_foto(perfil_id=perfil_id)

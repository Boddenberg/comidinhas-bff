from __future__ import annotations

from fastapi import APIRouter, Depends, File, Path, Query, UploadFile

from app.api.dependencies import get_manage_lugares_use_case
from app.modules.lugares.schemas import (
    FotoSchema,
    LugarCreateRequest,
    LugarFiltros,
    LugarListResponse,
    LugarResponse,
    LugarUpdateRequest,
    OrdemDirecao,
    OrdenarPor,
    ReordenarFotosRequest,
    StatusLugar,
)
from app.modules.lugares.use_cases import ManageLugaresUseCase

router = APIRouter(prefix="/lugares", tags=["lugares"])


@router.get("/", response_model=LugarListResponse, summary="Lista lugares com paginação, busca e filtros")
async def listar_lugares(
    grupo_id: str = Query(..., description="UUID do grupo (obrigatório)"),
    pagina: int = Query(default=1, ge=1),
    tamanho_pagina: int = Query(default=20, ge=1, le=100),
    busca: str | None = Query(default=None, max_length=120),
    categoria: str | None = Query(default=None, max_length=80),
    bairro: str | None = Query(default=None, max_length=80),
    status: StatusLugar | None = Query(default=None),
    favorito: bool | None = Query(default=None),
    faixa_preco: int | None = Query(default=None, ge=1, le=4),
    faixa_preco_min: int | None = Query(default=None, ge=1, le=4),
    faixa_preco_max: int | None = Query(default=None, ge=1, le=4),
    ordenar_por: OrdenarPor = Query(default=OrdenarPor.CRIADO_EM),
    direcao: OrdemDirecao = Query(default=OrdemDirecao.DESC),
    use_case: ManageLugaresUseCase = Depends(get_manage_lugares_use_case),
) -> LugarListResponse:
    filtros = LugarFiltros(
        grupo_id=grupo_id,
        pagina=pagina,
        tamanho_pagina=tamanho_pagina,
        busca=busca,
        categoria=categoria,
        bairro=bairro,
        status=status,
        favorito=favorito,
        faixa_preco=faixa_preco,
        faixa_preco_min=faixa_preco_min,
        faixa_preco_max=faixa_preco_max,
        ordenar_por=ordenar_por,
        direcao=direcao,
    )
    return await use_case.listar(filtros=filtros)


@router.post("/", response_model=LugarResponse, status_code=201, summary="Adiciona um novo lugar ao grupo")
async def criar_lugar(
    request: LugarCreateRequest,
    use_case: ManageLugaresUseCase = Depends(get_manage_lugares_use_case),
) -> LugarResponse:
    return await use_case.criar(request=request)


@router.get("/{lugar_id}", response_model=LugarResponse, summary="Retorna o detalhe de um lugar")
async def buscar_lugar(
    lugar_id: str = Path(..., min_length=8, max_length=64),
    use_case: ManageLugaresUseCase = Depends(get_manage_lugares_use_case),
) -> LugarResponse:
    return await use_case.buscar(lugar_id=lugar_id)


@router.patch("/{lugar_id}", response_model=LugarResponse, summary="Atualiza campos de um lugar")
async def atualizar_lugar(
    request: LugarUpdateRequest,
    lugar_id: str = Path(..., min_length=8, max_length=64),
    use_case: ManageLugaresUseCase = Depends(get_manage_lugares_use_case),
) -> LugarResponse:
    return await use_case.atualizar(lugar_id=lugar_id, request=request)


@router.delete("/{lugar_id}", summary="Remove um lugar e todas as suas fotos")
async def remover_lugar(
    lugar_id: str = Path(..., min_length=8, max_length=64),
    use_case: ManageLugaresUseCase = Depends(get_manage_lugares_use_case),
) -> dict:
    return await use_case.remover(lugar_id=lugar_id)


# ------------------------------------------------------------------ fotos


@router.post(
    "/{lugar_id}/fotos",
    response_model=FotoSchema,
    status_code=201,
    summary="Envia uma foto para o lugar (primeira vira capa automaticamente)",
)
async def adicionar_foto(
    file: UploadFile = File(...),
    lugar_id: str = Path(..., min_length=8, max_length=64),
    definir_como_capa: bool = Query(default=False),
    use_case: ManageLugaresUseCase = Depends(get_manage_lugares_use_case),
) -> FotoSchema:
    return await use_case.adicionar_foto(
        lugar_id=lugar_id,
        file=file,
        definir_como_capa=definir_como_capa,
    )


@router.patch(
    "/{lugar_id}/fotos/{foto_id}/capa",
    response_model=FotoSchema,
    summary="Define esta foto como a capa do lugar",
)
async def definir_capa(
    lugar_id: str = Path(..., min_length=8, max_length=64),
    foto_id: str = Path(..., min_length=8, max_length=64),
    use_case: ManageLugaresUseCase = Depends(get_manage_lugares_use_case),
) -> FotoSchema:
    return await use_case.definir_capa(lugar_id=lugar_id, foto_id=foto_id)


@router.patch(
    "/{lugar_id}/fotos/reordenar",
    response_model=LugarResponse,
    summary="Reordena as fotos enviando a lista de IDs na nova ordem",
)
async def reordenar_fotos(
    request: ReordenarFotosRequest,
    lugar_id: str = Path(..., min_length=8, max_length=64),
    use_case: ManageLugaresUseCase = Depends(get_manage_lugares_use_case),
) -> LugarResponse:
    return await use_case.reordenar_fotos(lugar_id=lugar_id, request=request)


@router.delete(
    "/{lugar_id}/fotos/{foto_id}",
    summary="Remove uma foto do lugar",
)
async def remover_foto(
    lugar_id: str = Path(..., min_length=8, max_length=64),
    foto_id: str = Path(..., min_length=8, max_length=64),
    use_case: ManageLugaresUseCase = Depends(get_manage_lugares_use_case),
) -> dict:
    return await use_case.remover_foto(lugar_id=lugar_id, foto_id=foto_id)

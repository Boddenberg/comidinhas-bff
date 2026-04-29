from __future__ import annotations

from fastapi import APIRouter, Depends, File, Path, Query, UploadFile

from app.api.dependencies import get_manage_grupos_use_case
from app.modules.grupos.schemas import (
    GrupoCreateRequest,
    GrupoConviteResponse,
    GrupoListResponse,
    GrupoMembroRequest,
    GrupoResponse,
    GrupoUpdateRequest,
    PapelMembroUpdateRequest,
    ResponderSolicitacaoGrupoRequest,
    SolicitacaoEntradaGrupoListResponse,
    SolicitacaoEntradaGrupoRequest,
    SolicitacaoEntradaGrupoSchema,
    StatusSolicitacaoGrupo,
)
from app.modules.grupos.use_cases import ManageGruposUseCase

router = APIRouter(prefix="/grupos", tags=["grupos"])


@router.get("/", response_model=GrupoListResponse, summary="Lista todos os grupos")
async def listar_grupos(
    perfil_id: str | None = Query(
        default=None,
        min_length=8,
        max_length=64,
        description="Quando informado, retorna apenas os espacos deste perfil.",
    ),
    use_case: ManageGruposUseCase = Depends(get_manage_grupos_use_case),
) -> GrupoListResponse:
    return await use_case.listar(perfil_id=perfil_id)


@router.post("/", response_model=GrupoResponse, status_code=201, summary="Cria um novo grupo ou casal")
async def criar_grupo(
    request: GrupoCreateRequest,
    use_case: ManageGruposUseCase = Depends(get_manage_grupos_use_case),
) -> GrupoResponse:
    return await use_case.criar(request=request)


@router.get("/codigo/{codigo}", response_model=GrupoResponse, summary="Busca grupo pelo codigo de 6 digitos")
async def buscar_grupo_por_codigo(
    codigo: str = Path(..., min_length=6, max_length=6, pattern=r"^\d{6}$"),
    use_case: ManageGruposUseCase = Depends(get_manage_grupos_use_case),
) -> GrupoResponse:
    return await use_case.buscar_por_codigo(codigo=codigo)


@router.post(
    "/codigo/{codigo}/solicitacoes",
    response_model=SolicitacaoEntradaGrupoSchema,
    status_code=201,
    summary="Solicita entrada em um grupo pelo codigo",
)
async def solicitar_entrada_no_grupo(
    request: SolicitacaoEntradaGrupoRequest,
    codigo: str = Path(..., min_length=6, max_length=6, pattern=r"^\d{6}$"),
    use_case: ManageGruposUseCase = Depends(get_manage_grupos_use_case),
) -> SolicitacaoEntradaGrupoSchema:
    return await use_case.solicitar_entrada(codigo=codigo, request=request)


@router.get("/{grupo_id}", response_model=GrupoResponse, summary="Retorna os detalhes de um grupo")
async def buscar_grupo(
    grupo_id: str = Path(..., min_length=8, max_length=64),
    use_case: ManageGruposUseCase = Depends(get_manage_grupos_use_case),
) -> GrupoResponse:
    return await use_case.buscar(grupo_id=grupo_id)


@router.get(
    "/{grupo_id}/convite",
    response_model=GrupoConviteResponse,
    summary="Gera link e texto de convite para compartilhar o grupo",
)
async def gerar_convite_grupo(
    grupo_id: str = Path(..., min_length=8, max_length=64),
    responsavel_perfil_id: str = Query(..., min_length=8, max_length=64),
    use_case: ManageGruposUseCase = Depends(get_manage_grupos_use_case),
) -> GrupoConviteResponse:
    return await use_case.gerar_convite(
        grupo_id=grupo_id,
        responsavel_perfil_id=responsavel_perfil_id,
    )


@router.patch("/{grupo_id}", response_model=GrupoResponse, summary="Atualiza nome, tipo, descrição ou membros")
async def atualizar_grupo(
    request: GrupoUpdateRequest,
    grupo_id: str = Path(..., min_length=8, max_length=64),
    use_case: ManageGruposUseCase = Depends(get_manage_grupos_use_case),
) -> GrupoResponse:
    return await use_case.atualizar(grupo_id=grupo_id, request=request)


@router.get(
    "/{grupo_id}/solicitacoes",
    response_model=SolicitacaoEntradaGrupoListResponse,
    summary="Lista solicitacoes de entrada pendentes ou respondidas",
)
async def listar_solicitacoes(
    grupo_id: str = Path(..., min_length=8, max_length=64),
    responsavel_perfil_id: str = Query(..., min_length=8, max_length=64),
    status: StatusSolicitacaoGrupo | None = Query(default=None),
    use_case: ManageGruposUseCase = Depends(get_manage_grupos_use_case),
) -> SolicitacaoEntradaGrupoListResponse:
    return await use_case.listar_solicitacoes(
        grupo_id=grupo_id,
        responsavel_perfil_id=responsavel_perfil_id,
        status=status,
    )


@router.post(
    "/{grupo_id}/solicitacoes/{solicitacao_id}/aceitar",
    response_model=GrupoResponse,
    summary="Aceita uma solicitacao de entrada no grupo",
)
async def aceitar_solicitacao(
    request: ResponderSolicitacaoGrupoRequest,
    grupo_id: str = Path(..., min_length=8, max_length=64),
    solicitacao_id: str = Path(..., min_length=8, max_length=64),
    use_case: ManageGruposUseCase = Depends(get_manage_grupos_use_case),
) -> GrupoResponse:
    return await use_case.aceitar_solicitacao(
        grupo_id=grupo_id,
        solicitacao_id=solicitacao_id,
        request=request,
    )


@router.post(
    "/{grupo_id}/solicitacoes/{solicitacao_id}/recusar",
    response_model=GrupoResponse,
    summary="Recusa uma solicitacao de entrada no grupo",
)
async def recusar_solicitacao(
    request: ResponderSolicitacaoGrupoRequest,
    grupo_id: str = Path(..., min_length=8, max_length=64),
    solicitacao_id: str = Path(..., min_length=8, max_length=64),
    use_case: ManageGruposUseCase = Depends(get_manage_grupos_use_case),
) -> GrupoResponse:
    return await use_case.recusar_solicitacao(
        grupo_id=grupo_id,
        solicitacao_id=solicitacao_id,
        request=request,
    )


@router.post(
    "/{grupo_id}/membros",
    response_model=GrupoResponse,
    status_code=201,
    summary="Adiciona um perfil cadastrado ao grupo/casal",
)
async def adicionar_membro(
    request: GrupoMembroRequest,
    grupo_id: str = Path(..., min_length=8, max_length=64),
    use_case: ManageGruposUseCase = Depends(get_manage_grupos_use_case),
) -> GrupoResponse:
    return await use_case.adicionar_membro(grupo_id=grupo_id, request=request)


@router.patch(
    "/{grupo_id}/membros/{perfil_id}/papel",
    response_model=GrupoResponse,
    summary="Define se um membro e administrador ou membro comum",
)
async def definir_papel_membro(
    request: PapelMembroUpdateRequest,
    grupo_id: str = Path(..., min_length=8, max_length=64),
    perfil_id: str = Path(..., min_length=8, max_length=64),
    use_case: ManageGruposUseCase = Depends(get_manage_grupos_use_case),
) -> GrupoResponse:
    return await use_case.definir_papel_membro(
        grupo_id=grupo_id,
        perfil_id=perfil_id,
        request=request,
    )


@router.delete(
    "/{grupo_id}/membros/{perfil_id}",
    response_model=GrupoResponse,
    summary="Remove um perfil do grupo/casal",
)
async def remover_membro(
    grupo_id: str = Path(..., min_length=8, max_length=64),
    perfil_id: str = Path(..., min_length=8, max_length=64),
    responsavel_perfil_id: str = Query(..., min_length=8, max_length=64),
    use_case: ManageGruposUseCase = Depends(get_manage_grupos_use_case),
) -> GrupoResponse:
    return await use_case.remover_membro(
        grupo_id=grupo_id,
        perfil_id=perfil_id,
        responsavel_perfil_id=responsavel_perfil_id,
    )


@router.post(
    "/{grupo_id}/foto",
    response_model=GrupoResponse,
    summary="Envia ou substitui a foto do grupo",
)
async def upload_foto_grupo(
    file: UploadFile = File(...),
    grupo_id: str = Path(..., min_length=8, max_length=64),
    responsavel_perfil_id: str = Query(..., min_length=8, max_length=64),
    use_case: ManageGruposUseCase = Depends(get_manage_grupos_use_case),
) -> GrupoResponse:
    return await use_case.upload_foto(
        grupo_id=grupo_id,
        responsavel_perfil_id=responsavel_perfil_id,
        file=file,
    )


@router.delete(
    "/{grupo_id}/foto",
    response_model=GrupoResponse,
    summary="Remove a foto do grupo",
)
async def remover_foto_grupo(
    grupo_id: str = Path(..., min_length=8, max_length=64),
    responsavel_perfil_id: str = Query(..., min_length=8, max_length=64),
    use_case: ManageGruposUseCase = Depends(get_manage_grupos_use_case),
) -> GrupoResponse:
    return await use_case.remover_foto(
        grupo_id=grupo_id,
        responsavel_perfil_id=responsavel_perfil_id,
    )


@router.delete("/{grupo_id}", summary="Remove um grupo e todos os seus lugares")
async def remover_grupo(
    grupo_id: str = Path(..., min_length=8, max_length=64),
    responsavel_perfil_id: str = Query(..., min_length=8, max_length=64),
    use_case: ManageGruposUseCase = Depends(get_manage_grupos_use_case),
) -> dict:
    return await use_case.remover(
        grupo_id=grupo_id,
        responsavel_perfil_id=responsavel_perfil_id,
    )

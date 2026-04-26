from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Path

from app.api.dependencies import get_manage_groups_use_case
from app.api.v1.routes.profiles import get_access_token
from app.modules.groups.schemas import (
    GroupCreateRequest,
    GroupListResponse,
    GroupMemberAddRequest,
    GroupResponse,
    GroupUpdateRequest,
    ProfileContextResponse,
    SeedFilipeVictorRequest,
    SeedFilipeVictorResponse,
    SetActiveGroupRequest,
)
from app.modules.groups.use_cases import ManageGroupsUseCase

router = APIRouter(prefix="/groups", tags=["groups"])


@router.get(
    "/me/context",
    response_model=ProfileContextResponse,
    summary="Retorna o contexto atual do usuario: perfil, grupo ativo e papel",
)
async def get_my_context(
    access_token: str = Depends(get_access_token),
    use_case: ManageGroupsUseCase = Depends(get_manage_groups_use_case),
) -> ProfileContextResponse:
    return await use_case.get_my_context(access_token=access_token)


@router.get(
    "/",
    response_model=GroupListResponse,
    summary="Lista todos os grupos/casais do usuario autenticado",
)
async def list_my_groups(
    access_token: str = Depends(get_access_token),
    use_case: ManageGroupsUseCase = Depends(get_manage_groups_use_case),
) -> GroupListResponse:
    return await use_case.list_my_groups(access_token=access_token)


@router.post(
    "/",
    response_model=GroupResponse,
    status_code=201,
    summary="Cria um novo grupo ou casal",
)
async def create_group(
    request: GroupCreateRequest,
    access_token: str = Depends(get_access_token),
    use_case: ManageGroupsUseCase = Depends(get_manage_groups_use_case),
) -> GroupResponse:
    return await use_case.create_group(access_token=access_token, request=request)


@router.get(
    "/{group_id}",
    response_model=GroupResponse,
    summary="Retorna os detalhes de um grupo, incluindo membros",
)
async def get_group(
    group_id: str = Path(..., min_length=8, max_length=64),
    access_token: str = Depends(get_access_token),
    use_case: ManageGroupsUseCase = Depends(get_manage_groups_use_case),
) -> GroupResponse:
    return await use_case.get_group(access_token=access_token, group_id=group_id)


@router.patch(
    "/{group_id}",
    response_model=GroupResponse,
    summary="Atualiza nome, tipo ou descricao do grupo (somente o dono)",
)
async def update_group(
    request: GroupUpdateRequest,
    group_id: str = Path(..., min_length=8, max_length=64),
    access_token: str = Depends(get_access_token),
    use_case: ManageGroupsUseCase = Depends(get_manage_groups_use_case),
) -> GroupResponse:
    return await use_case.update_group(
        access_token=access_token,
        group_id=group_id,
        request=request,
    )


@router.delete(
    "/{group_id}",
    summary="Remove o grupo (somente o dono)",
)
async def delete_group(
    group_id: str = Path(..., min_length=8, max_length=64),
    access_token: str = Depends(get_access_token),
    use_case: ManageGroupsUseCase = Depends(get_manage_groups_use_case),
) -> dict:
    return await use_case.delete_group(access_token=access_token, group_id=group_id)


@router.post(
    "/{group_id}/members",
    response_model=GroupResponse,
    status_code=201,
    summary="Adiciona um membro ao grupo (somente o dono)",
)
async def add_member(
    request: GroupMemberAddRequest,
    group_id: str = Path(..., min_length=8, max_length=64),
    access_token: str = Depends(get_access_token),
    use_case: ManageGroupsUseCase = Depends(get_manage_groups_use_case),
) -> GroupResponse:
    return await use_case.add_member(
        access_token=access_token,
        group_id=group_id,
        request=request,
    )


@router.delete(
    "/{group_id}/members/{profile_id}",
    response_model=GroupResponse,
    summary="Remove um membro do grupo (dono pode remover qualquer um; membro pode remover a si mesmo)",
)
async def remove_member(
    group_id: str = Path(..., min_length=8, max_length=64),
    profile_id: str = Path(..., min_length=8, max_length=64),
    access_token: str = Depends(get_access_token),
    use_case: ManageGroupsUseCase = Depends(get_manage_groups_use_case),
) -> GroupResponse:
    return await use_case.remove_member(
        access_token=access_token,
        group_id=group_id,
        profile_id=profile_id,
    )


@router.post(
    "/active",
    response_model=ProfileContextResponse,
    summary="Define o grupo ativo do usuario para listagem de lugares e home",
)
async def set_active_group(
    request: SetActiveGroupRequest = Body(default_factory=SetActiveGroupRequest),
    access_token: str = Depends(get_access_token),
    use_case: ManageGroupsUseCase = Depends(get_manage_groups_use_case),
) -> ProfileContextResponse:
    return await use_case.set_active_group(
        access_token=access_token,
        request=request,
    )


@router.post(
    "/seed/filipe-victor",
    response_model=SeedFilipeVictorResponse,
    status_code=201,
    summary="Cria o grupo 'Filipe e Victor' com os perfis ja existentes (ambos precisam ter conta)",
)
async def seed_filipe_victor(
    request: SeedFilipeVictorRequest = Body(default_factory=SeedFilipeVictorRequest),
    access_token: str = Depends(get_access_token),
    use_case: ManageGroupsUseCase = Depends(get_manage_groups_use_case),
) -> SeedFilipeVictorResponse:
    return await use_case.seed_filipe_victor(
        access_token=access_token,
        request=request,
    )

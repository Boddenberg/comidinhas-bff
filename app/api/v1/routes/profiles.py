from __future__ import annotations

from fastapi import APIRouter, Body, Depends, File, UploadFile
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.dependencies import get_manage_profiles_use_case
from app.core.errors import AuthenticationError
from app.modules.profiles.schemas import (
    ActionResponse,
    ProfileAuthResponse,
    ProfileCredentialsUpdateRequest,
    ProfileMeResponse,
    ProfileRefreshSessionRequest,
    ProfileSignInRequest,
    ProfileSignOutRequest,
    ProfileSignUpRequest,
    ProfileUpdateRequest,
)
from app.modules.profiles.use_cases import ManageProfilesUseCase

router = APIRouter(prefix="/profiles", tags=["profiles"])

bearer_scheme = HTTPBearer(auto_error=False)


def get_access_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError(
            "Envie o header Authorization com um Bearer token valido.",
        )
    return credentials.credentials


@router.post(
    "/signup",
    response_model=ProfileAuthResponse,
    status_code=201,
    summary="Cria uma conta e um perfil base no Supabase",
)
async def sign_up(
    request: ProfileSignUpRequest,
    use_case: ManageProfilesUseCase = Depends(get_manage_profiles_use_case),
) -> ProfileAuthResponse:
    return await use_case.sign_up(request)


@router.post(
    "/signin",
    response_model=ProfileAuthResponse,
    summary="Autentica por email e senha no Supabase",
)
async def sign_in(
    request: ProfileSignInRequest,
    use_case: ManageProfilesUseCase = Depends(get_manage_profiles_use_case),
) -> ProfileAuthResponse:
    return await use_case.sign_in(request)


@router.post(
    "/refresh",
    response_model=ProfileAuthResponse,
    summary="Renova a sessao atual usando refresh token",
)
async def refresh_session(
    request: ProfileRefreshSessionRequest,
    use_case: ManageProfilesUseCase = Depends(get_manage_profiles_use_case),
) -> ProfileAuthResponse:
    return await use_case.refresh_session(request)


@router.post(
    "/signout",
    response_model=ActionResponse,
    summary="Encerra a sessao atual no Supabase",
)
async def sign_out(
    request: ProfileSignOutRequest | None = Body(default=None),
    access_token: str = Depends(get_access_token),
    use_case: ManageProfilesUseCase = Depends(get_manage_profiles_use_case),
) -> ActionResponse:
    return await use_case.sign_out(
        access_token=access_token,
        request=request or ProfileSignOutRequest(),
    )


@router.post(
    "/me/reauthenticate",
    response_model=ActionResponse,
    summary="Pede um nonce de reautenticacao para trocar senha com seguranca",
)
async def reauthenticate(
    access_token: str = Depends(get_access_token),
    use_case: ManageProfilesUseCase = Depends(get_manage_profiles_use_case),
) -> ActionResponse:
    return await use_case.reauthenticate(access_token=access_token)


@router.get(
    "/me",
    response_model=ProfileMeResponse,
    summary="Retorna o perfil atual do usuario autenticado",
)
async def get_me(
    access_token: str = Depends(get_access_token),
    use_case: ManageProfilesUseCase = Depends(get_manage_profiles_use_case),
) -> ProfileMeResponse:
    return await use_case.get_me(access_token=access_token)


@router.patch(
    "/me",
    response_model=ProfileMeResponse,
    summary="Atualiza os campos do perfil publico do usuario",
)
async def update_me(
    request: ProfileUpdateRequest,
    access_token: str = Depends(get_access_token),
    use_case: ManageProfilesUseCase = Depends(get_manage_profiles_use_case),
) -> ProfileMeResponse:
    return await use_case.update_me(
        access_token=access_token,
        request=request,
    )


@router.patch(
    "/me/credentials",
    response_model=ProfileMeResponse,
    summary="Troca username, email e senha do usuario",
)
async def update_credentials(
    request: ProfileCredentialsUpdateRequest,
    access_token: str = Depends(get_access_token),
    use_case: ManageProfilesUseCase = Depends(get_manage_profiles_use_case),
) -> ProfileMeResponse:
    return await use_case.update_credentials(
        access_token=access_token,
        request=request,
    )


@router.post(
    "/me/photo",
    response_model=ProfileMeResponse,
    summary="Envia ou substitui a foto do perfil",
)
async def upload_photo(
    file: UploadFile = File(...),
    access_token: str = Depends(get_access_token),
    use_case: ManageProfilesUseCase = Depends(get_manage_profiles_use_case),
) -> ProfileMeResponse:
    return await use_case.upload_photo(
        access_token=access_token,
        file=file,
    )


@router.delete(
    "/me/photo",
    response_model=ProfileMeResponse,
    summary="Remove a foto atual do perfil",
)
async def delete_photo(
    access_token: str = Depends(get_access_token),
    use_case: ManageProfilesUseCase = Depends(get_manage_profiles_use_case),
) -> ProfileMeResponse:
    return await use_case.delete_photo(access_token=access_token)


@router.delete(
    "/me",
    response_model=ActionResponse,
    summary="Exclui apenas os dados do perfil em public.profiles",
)
async def delete_profile(
    access_token: str = Depends(get_access_token),
    use_case: ManageProfilesUseCase = Depends(get_manage_profiles_use_case),
) -> ActionResponse:
    return await use_case.delete_profile(access_token=access_token)


@router.delete(
    "/me/account",
    response_model=ActionResponse,
    summary="Exclui a conta de autenticacao e o perfil associado",
)
async def delete_account(
    access_token: str = Depends(get_access_token),
    use_case: ManageProfilesUseCase = Depends(get_manage_profiles_use_case),
) -> ActionResponse:
    return await use_case.delete_account(access_token=access_token)

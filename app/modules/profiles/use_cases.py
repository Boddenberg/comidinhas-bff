from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import UploadFile

from app.core.errors import BadRequestError, ExternalServiceError
from app.integrations.supabase.client import SupabaseClient
from app.modules.profiles.schemas import (
    ActionResponse,
    AuthenticatedUserResponse,
    ProfileAuthResponse,
    ProfileCredentialsUpdateRequest,
    ProfileMeResponse,
    ProfileResponse,
    ProfileSessionResponse,
    ProfileSignInRequest,
    ProfileSignOutRequest,
    ProfileSignUpRequest,
    ProfileUpdateRequest,
    ProfileRefreshSessionRequest,
)


class ManageProfilesUseCase:
    ALLOWED_IMAGE_TYPES = {
        "image/gif": "gif",
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }

    def __init__(self, client: SupabaseClient) -> None:
        self._client = client

    async def sign_up(self, request: ProfileSignUpRequest) -> ProfileAuthResponse:
        auth_response = await self._client.sign_up(
            email=request.email,
            password=request.password,
            metadata={
                "username": request.username,
                "full_name": request.full_name,
            },
        )
        user_payload = self._require_user(auth_response.get("user"))
        session_payload = auth_response.get("session")
        profile: ProfileResponse | None = None

        if isinstance(session_payload, dict):
            raw_profile = await self._client.upsert_profile(
                access_token=session_payload["access_token"],
                profile_data={
                    "id": user_payload["id"],
                    **request.model_dump(exclude={"password"}, exclude_none=True),
                    "email": user_payload.get("email") or request.email,
                },
            )
            profile = self._map_profile(raw_profile)

        message = None
        if auth_response.get("email_confirmation_required"):
            message = (
                "Cadastro criado. Se a confirmacao de email estiver ativa no Supabase, confirme o endereco antes de entrar."
            )

        return ProfileAuthResponse(
            user=self._map_user(user_payload),
            profile=profile,
            session=self._map_session(session_payload),
            email_confirmation_required=bool(auth_response.get("email_confirmation_required")),
            message=message,
        )

    async def sign_in(self, request: ProfileSignInRequest) -> ProfileAuthResponse:
        auth_response = await self._client.sign_in(
            email=request.email,
            password=request.password,
        )
        user_payload = self._require_user(auth_response.get("user"))
        session_payload = self._require_session(auth_response.get("session"))
        profile = await self._ensure_profile(
            access_token=session_payload["access_token"],
            user_payload=user_payload,
        )

        return ProfileAuthResponse(
            user=self._map_user(user_payload),
            profile=profile,
            session=self._map_session(session_payload),
        )

    async def refresh_session(
        self,
        request: ProfileRefreshSessionRequest,
    ) -> ProfileAuthResponse:
        auth_response = await self._client.refresh_session(
            refresh_token=request.refresh_token,
        )
        user_payload = self._require_user(auth_response.get("user"))
        session_payload = self._require_session(auth_response.get("session"))
        profile = await self._ensure_profile(
            access_token=session_payload["access_token"],
            user_payload=user_payload,
        )

        return ProfileAuthResponse(
            user=self._map_user(user_payload),
            profile=profile,
            session=self._map_session(session_payload),
        )

    async def sign_out(
        self,
        *,
        access_token: str,
        request: ProfileSignOutRequest,
    ) -> ActionResponse:
        await self._client.sign_out(
            access_token=access_token,
            scope=request.scope,
        )
        return ActionResponse(message="Sessao encerrada com sucesso.")

    async def reauthenticate(self, *, access_token: str) -> ActionResponse:
        await self._client.reauthenticate(access_token=access_token)
        return ActionResponse(
            message="Se o projeto exigir reautenticacao, o Supabase enviou um nonce para o canal configurado do usuario.",
        )

    async def get_me(self, *, access_token: str) -> ProfileMeResponse:
        user_payload = await self._client.get_user(access_token=access_token)
        profile = await self._ensure_profile(
            access_token=access_token,
            user_payload=user_payload,
        )
        return ProfileMeResponse(
            user=self._map_user(user_payload),
            profile=profile,
        )

    async def update_me(
        self,
        *,
        access_token: str,
        request: ProfileUpdateRequest,
    ) -> ProfileMeResponse:
        payload = request.model_dump(exclude_unset=True)
        if not payload:
            raise BadRequestError("Informe ao menos um campo para atualizar o perfil.")

        user_payload = await self._client.get_user(access_token=access_token)
        raw_profile = await self._client.upsert_profile(
            access_token=access_token,
            profile_data={
                "id": user_payload["id"],
                **payload,
            },
        )
        return ProfileMeResponse(
            user=self._map_user(user_payload),
            profile=self._map_profile(raw_profile),
        )

    async def update_credentials(
        self,
        *,
        access_token: str,
        request: ProfileCredentialsUpdateRequest,
    ) -> ProfileMeResponse:
        if not request.model_fields_set:
            raise BadRequestError(
                "Informe ao menos um campo entre username, email ou password para atualizar.",
            )

        current_user = await self._client.get_user(access_token=access_token)
        attributes: dict[str, Any] = {}

        if "email" in request.model_fields_set:
            attributes["email"] = request.email

        if "password" in request.model_fields_set:
            attributes["password"] = request.password

        if "nonce" in request.model_fields_set and request.nonce:
            attributes["nonce"] = request.nonce

        if "username" in request.model_fields_set:
            user_metadata = dict(current_user.get("user_metadata") or {})
            if request.username is None:
                user_metadata.pop("username", None)
            else:
                user_metadata["username"] = request.username
            attributes["data"] = user_metadata

        updated_user = await self._client.update_user(
            access_token=access_token,
            attributes=attributes,
            email_redirect_to=request.email_redirect_to,
        )
        raw_profile = await self._client.upsert_profile(
            access_token=access_token,
            profile_data={
                "id": updated_user["id"],
                "email": updated_user.get("email"),
                **(
                    {"username": request.username}
                    if "username" in request.model_fields_set
                    else {}
                ),
            },
        )

        return ProfileMeResponse(
            user=self._map_user(updated_user),
            profile=self._map_profile(raw_profile),
        )

    async def upload_photo(
        self,
        *,
        access_token: str,
        file: UploadFile,
    ) -> ProfileMeResponse:
        user_payload = await self._client.get_user(access_token=access_token)
        profile = await self._ensure_profile(
            access_token=access_token,
            user_payload=user_payload,
        )

        content_type = file.content_type or ""
        extension = self.ALLOWED_IMAGE_TYPES.get(content_type)
        if extension is None:
            raise BadRequestError(
                "Envie uma imagem JPG, PNG, WEBP ou GIF para a foto do perfil.",
            )

        content = await file.read()
        if not content:
            raise BadRequestError("O arquivo enviado esta vazio.")

        if len(content) > self._client.max_profile_photo_bytes:
            raise BadRequestError(
                f"A foto excede o limite de {self._client.max_profile_photo_bytes} bytes configurado para o perfil.",
            )

        object_path = f"{user_payload['id']}/avatar-{uuid4().hex}.{extension}"
        upload = await self._client.upload_profile_photo(
            access_token=access_token,
            object_path=object_path,
            content=content,
            filename=file.filename or f"avatar.{extension}",
            content_type=content_type,
        )

        raw_profile = await self._client.upsert_profile(
            access_token=access_token,
            profile_data={
                "id": user_payload["id"],
                "avatar_path": upload["path"],
                "avatar_url": upload["public_url"],
            },
        )

        if profile.avatar_path and profile.avatar_path != upload["path"]:
            await self._safe_remove_photo(
                access_token=access_token,
                object_path=profile.avatar_path,
            )

        return ProfileMeResponse(
            user=self._map_user(user_payload),
            profile=self._map_profile(raw_profile),
        )

    async def delete_photo(self, *, access_token: str) -> ProfileMeResponse:
        user_payload = await self._client.get_user(access_token=access_token)
        profile = await self._ensure_profile(
            access_token=access_token,
            user_payload=user_payload,
        )

        if profile.avatar_path:
            await self._safe_remove_photo(
                access_token=access_token,
                object_path=profile.avatar_path,
            )

        raw_profile = await self._client.upsert_profile(
            access_token=access_token,
            profile_data={
                "id": user_payload["id"],
                "avatar_path": None,
                "avatar_url": None,
            },
        )

        return ProfileMeResponse(
            user=self._map_user(user_payload),
            profile=self._map_profile(raw_profile),
        )

    async def delete_profile(self, *, access_token: str) -> ActionResponse:
        user_payload = await self._client.get_user(access_token=access_token)
        existing_profile = await self._client.get_profile(
            access_token=access_token,
            user_id=user_payload["id"],
        )

        if isinstance(existing_profile, dict):
            avatar_path = existing_profile.get("avatar_path")
            if isinstance(avatar_path, str) and avatar_path.strip():
                await self._safe_remove_photo(
                    access_token=access_token,
                    object_path=avatar_path,
                )

        await self._client.delete_profile(
            access_token=access_token,
            user_id=user_payload["id"],
        )
        return ActionResponse(
            message="Os dados do perfil foram removidos. A conta de autenticacao continua ativa.",
        )

    async def delete_account(self, *, access_token: str) -> ActionResponse:
        user_payload = await self._client.get_user(access_token=access_token)
        existing_profile = await self._client.get_profile(
            access_token=access_token,
            user_id=user_payload["id"],
        )

        if isinstance(existing_profile, dict):
            avatar_path = existing_profile.get("avatar_path")
            if isinstance(avatar_path, str) and avatar_path.strip():
                await self._safe_remove_photo(
                    access_token=access_token,
                    object_path=avatar_path,
                )

        await self._client.delete_my_account(access_token=access_token)
        return ActionResponse(
            message="Conta removida com sucesso. O perfil em public.profiles foi excluido junto com o usuario.",
        )

    async def _ensure_profile(
        self,
        *,
        access_token: str,
        user_payload: dict[str, Any],
    ) -> ProfileResponse:
        existing_profile = await self._client.get_profile(
            access_token=access_token,
            user_id=user_payload["id"],
        )
        if isinstance(existing_profile, dict):
            return self._map_profile(existing_profile)

        raw_profile = await self._client.upsert_profile(
            access_token=access_token,
            profile_data={
                "id": user_payload["id"],
                "email": user_payload.get("email"),
                "username": self._extract_metadata_string(user_payload, "username"),
                "full_name": self._extract_metadata_string(user_payload, "full_name"),
            },
        )
        return self._map_profile(raw_profile)

    async def _safe_remove_photo(self, *, access_token: str, object_path: str) -> None:
        try:
            await self._client.remove_profile_photo(
                access_token=access_token,
                object_path=object_path,
            )
        except ExternalServiceError:
            return

    @staticmethod
    def _extract_metadata_string(user_payload: dict[str, Any], key: str) -> str | None:
        user_metadata = user_payload.get("user_metadata")
        if not isinstance(user_metadata, dict):
            return None
        value = user_metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    @staticmethod
    def _require_user(user_payload: Any) -> dict[str, Any]:
        if isinstance(user_payload, dict):
            return user_payload
        raise ExternalServiceError(
            "supabase",
            "O Supabase nao retornou o usuario autenticado esperado.",
        )

    @staticmethod
    def _require_session(session_payload: Any) -> dict[str, Any]:
        if isinstance(session_payload, dict):
            return session_payload
        raise ExternalServiceError(
            "supabase",
            "O Supabase nao retornou a sessao esperada.",
        )

    @staticmethod
    def _map_user(payload: dict[str, Any]) -> AuthenticatedUserResponse:
        user_metadata = payload.get("user_metadata")
        return AuthenticatedUserResponse(
            id=str(payload.get("id", "")),
            email=payload.get("email"),
            email_confirmed_at=payload.get("email_confirmed_at"),
            last_sign_in_at=payload.get("last_sign_in_at"),
            user_metadata=user_metadata if isinstance(user_metadata, dict) else {},
        )

    @staticmethod
    def _map_profile(payload: dict[str, Any]) -> ProfileResponse:
        preferences = payload.get("preferences")
        extra_data = payload.get("extra_data")
        return ProfileResponse(
            id=str(payload.get("id", "")),
            email=payload.get("email"),
            username=payload.get("username"),
            full_name=payload.get("full_name"),
            phone=payload.get("phone"),
            birth_date=payload.get("birth_date"),
            city=payload.get("city"),
            state=payload.get("state"),
            bio=payload.get("bio"),
            favorite_cuisine=payload.get("favorite_cuisine"),
            avatar_path=payload.get("avatar_path"),
            avatar_url=payload.get("avatar_url"),
            preferences=preferences if isinstance(preferences, dict) else {},
            extra_data=extra_data if isinstance(extra_data, dict) else {},
            created_at=payload.get("created_at"),
            updated_at=payload.get("updated_at"),
        )

    @staticmethod
    def _map_session(payload: Any) -> ProfileSessionResponse | None:
        if not isinstance(payload, dict):
            return None
        return ProfileSessionResponse(
            access_token=payload["access_token"],
            refresh_token=payload["refresh_token"],
            token_type=payload.get("token_type", "bearer"),
            expires_in=payload.get("expires_in"),
            expires_at=payload.get("expires_at"),
        )

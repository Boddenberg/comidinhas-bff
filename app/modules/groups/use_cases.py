from __future__ import annotations

from typing import Any

from app.core.errors import BadRequestError, ConflictError, NotFoundError
from app.integrations.supabase.client import SupabaseClient
from app.modules.groups.schemas import (
    GroupCreateRequest,
    GroupListResponse,
    GroupMemberAddRequest,
    GroupMemberResponse,
    GroupMemberRole,
    GroupResponse,
    GroupSummaryResponse,
    GroupType,
    GroupUpdateRequest,
    ProfileContextResponse,
    SeedFilipeVictorRequest,
    SeedFilipeVictorResponse,
    SetActiveGroupRequest,
)


class ManageGroupsUseCase:
    def __init__(self, client: SupabaseClient) -> None:
        self._client = client

    async def get_my_context(self, *, access_token: str) -> ProfileContextResponse:
        user = await self._client.get_user(access_token=access_token)
        profile = await self._ensure_profile(access_token=access_token, user_payload=user)
        memberships = await self._client.list_user_memberships(
            access_token=access_token,
            user_id=str(user["id"]),
        )
        role_by_group = self._roles_by_group(memberships)
        groups = await self._client.list_groups(access_token=access_token)
        group_items = [
            self._map_summary(raw, role_by_group.get(str(raw.get("id")), GroupMemberRole.MEMBER.value))
            for raw in groups
            if isinstance(raw, dict)
        ]

        active_group: GroupResponse | None = None
        active_role: GroupMemberRole | None = None
        active_group_id = profile.get("active_group_id")
        if isinstance(active_group_id, str) and active_group_id:
            active_group = await self.get_group(
                access_token=access_token,
                group_id=active_group_id,
            )
            active_role = self._role_from_raw(role_by_group.get(active_group.id))

        return ProfileContextResponse(
            user_id=str(user["id"]),
            profile_id=str(profile.get("id", user["id"])),
            email=profile.get("email") or user.get("email"),
            username=profile.get("username"),
            full_name=profile.get("full_name"),
            avatar_url=profile.get("avatar_url"),
            active_group=active_group,
            active_role=active_role,
            groups=group_items,
        )

    async def list_my_groups(self, *, access_token: str) -> GroupListResponse:
        user = await self._client.get_user(access_token=access_token)
        memberships = await self._client.list_user_memberships(
            access_token=access_token,
            user_id=str(user["id"]),
        )
        role_by_group = self._roles_by_group(memberships)
        groups = await self._client.list_groups(access_token=access_token)
        items = [
            self._map_summary(raw, role_by_group.get(str(raw.get("id")), GroupMemberRole.MEMBER.value))
            for raw in groups
            if isinstance(raw, dict)
        ]
        return GroupListResponse(items=items)

    async def get_group(self, *, access_token: str, group_id: str) -> GroupResponse:
        raw = await self._client.get_group_with_members(
            access_token=access_token,
            group_id=group_id,
        )
        if raw is None:
            raise NotFoundError("Grupo nao encontrado.")
        return self._map_group(raw)

    async def create_group(self, *, access_token: str, request: GroupCreateRequest) -> GroupResponse:
        user = await self._client.get_user(access_token=access_token)
        owner_id = str(user["id"])
        await self._ensure_profile(access_token=access_token, user_payload=user)

        partner_id: str | None = request.partner_profile_id
        if partner_id is None and request.partner_email:
            partner_id = await self._resolve_profile_id_by_email(
                access_token=access_token,
                email=request.partner_email,
            )
            if partner_id is None:
                raise NotFoundError(
                    f"Nao encontrei um perfil com o email {request.partner_email}.",
                )

        if partner_id == owner_id:
            raise BadRequestError("O parceiro nao pode ser voce mesmo.")

        payload: dict[str, Any] = {
            "name": request.name,
            "type": request.type.value,
            "description": request.description,
            "owner_id": owner_id,
            "created_by": owner_id,
        }
        created = await self._client.insert_group(
            access_token=access_token,
            payload=payload,
        )

        if partner_id is not None:
            try:
                await self._client.insert_group_member(
                    access_token=access_token,
                    payload={
                        "group_id": created["id"],
                        "profile_id": partner_id,
                        "role": GroupMemberRole.MEMBER.value,
                        "invited_by": owner_id,
                    },
                )
            except ConflictError:
                pass

        return await self.get_group(access_token=access_token, group_id=str(created["id"]))

    async def update_group(
        self,
        *,
        access_token: str,
        group_id: str,
        request: GroupUpdateRequest,
    ) -> GroupResponse:
        user = await self._client.get_user(access_token=access_token)
        payload = request.model_dump(exclude_unset=True)
        if "type" in payload and isinstance(payload["type"], GroupType):
            payload["type"] = payload["type"].value
        if not payload:
            raise BadRequestError("Informe ao menos um campo para atualizar o grupo.")
        payload["updated_by"] = user["id"]

        await self._client.update_group(
            access_token=access_token,
            group_id=group_id,
            payload=payload,
        )
        return await self.get_group(access_token=access_token, group_id=group_id)

    async def delete_group(self, *, access_token: str, group_id: str) -> dict[str, Any]:
        await self._client.delete_group(access_token=access_token, group_id=group_id)
        return {"success": True, "message": "Grupo removido com sucesso."}

    async def add_member(
        self,
        *,
        access_token: str,
        group_id: str,
        request: GroupMemberAddRequest,
    ) -> GroupResponse:
        user = await self._client.get_user(access_token=access_token)
        profile_id = request.profile_id
        if profile_id is None and request.email:
            profile_id = await self._resolve_profile_id_by_email(
                access_token=access_token,
                email=request.email,
            )
            if profile_id is None:
                raise NotFoundError(
                    f"Nao encontrei um perfil com o email {request.email}.",
                )

        if profile_id is None:
            raise BadRequestError("Informe profile_id ou email do membro a adicionar.")

        await self._client.insert_group_member(
            access_token=access_token,
            payload={
                "group_id": group_id,
                "profile_id": profile_id,
                "role": request.role.value,
                "invited_by": user["id"],
            },
        )
        return await self.get_group(access_token=access_token, group_id=group_id)

    async def remove_member(
        self,
        *,
        access_token: str,
        group_id: str,
        profile_id: str,
    ) -> GroupResponse:
        await self._client.delete_group_member(
            access_token=access_token,
            group_id=group_id,
            profile_id=profile_id,
        )
        return await self.get_group(access_token=access_token, group_id=group_id)

    async def set_active_group(
        self,
        *,
        access_token: str,
        request: SetActiveGroupRequest,
    ) -> ProfileContextResponse:
        await self._client.call_rpc(
            access_token=access_token,
            function_name="set_active_group",
            payload={"target_group_id": request.group_id},
        )
        return await self.get_my_context(access_token=access_token)

    async def seed_filipe_victor(
        self,
        *,
        access_token: str,
        request: SeedFilipeVictorRequest,
    ) -> SeedFilipeVictorResponse:
        result = await self._client.call_rpc(
            access_token=access_token,
            function_name="seed_filipe_victor",
            payload={
                "filipe_email": request.filipe_email,
                "victor_email": request.victor_email,
            },
        )
        group_id = result if isinstance(result, str) else None
        if group_id is None:
            raise BadRequestError(
                "Nao foi possivel criar o casal Filipe e Victor com os dados informados.",
            )
        return SeedFilipeVictorResponse(group_id=group_id)

    async def _ensure_profile(
        self,
        *,
        access_token: str,
        user_payload: dict[str, Any],
    ) -> dict[str, Any]:
        profile = await self._client.get_profile(
            access_token=access_token,
            user_id=str(user_payload["id"]),
        )
        if isinstance(profile, dict):
            return profile

        metadata = user_payload.get("user_metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        return await self._client.upsert_profile(
            access_token=access_token,
            profile_data={
                "id": user_payload["id"],
                "email": user_payload.get("email"),
                "username": metadata.get("username"),
                "full_name": metadata.get("full_name"),
            },
        )

    async def _resolve_profile_id_by_email(
        self,
        *,
        access_token: str,
        email: str,
    ) -> str | None:
        profile = await self._client.find_profile_by_email(
            access_token=access_token,
            email=email,
        )
        if isinstance(profile, dict):
            value = profile.get("id")
            if isinstance(value, str) and value:
                return value
        return None

    @staticmethod
    def _roles_by_group(memberships: list[Any]) -> dict[str, str]:
        roles: dict[str, str] = {}
        for membership in memberships:
            if not isinstance(membership, dict):
                continue
            group_id = membership.get("group_id")
            role = membership.get("role")
            if isinstance(group_id, str) and isinstance(role, str):
                roles[group_id] = role
        return roles

    @staticmethod
    def _role_from_raw(raw: str | None) -> GroupMemberRole | None:
        if raw is None:
            return None
        try:
            return GroupMemberRole(raw)
        except ValueError:
            return GroupMemberRole.MEMBER

    @classmethod
    def _map_summary(cls, raw: dict[str, Any], role: str) -> GroupSummaryResponse:
        return GroupSummaryResponse(
            id=str(raw.get("id", "")),
            name=str(raw.get("name", "")),
            type=GroupType(raw.get("type") or GroupType.GROUP.value),
            description=raw.get("description"),
            owner_id=str(raw.get("owner_id", "")),
            role=cls._role_from_raw(role) or GroupMemberRole.MEMBER,
            member_count=int(raw.get("member_count") or 0),
        )

    @classmethod
    def _map_group(cls, raw: dict[str, Any]) -> GroupResponse:
        members_raw = raw.get("members") or raw.get("group_members") or []
        members: list[GroupMemberResponse] = []
        if isinstance(members_raw, list):
            for item in members_raw:
                if not isinstance(item, dict):
                    continue
                profile = item.get("profile") if isinstance(item.get("profile"), dict) else {}
                role = cls._role_from_raw(item.get("role")) or GroupMemberRole.MEMBER
                members.append(
                    GroupMemberResponse(
                        profile_id=str(item.get("profile_id") or profile.get("id") or ""),
                        role=role,
                        full_name=profile.get("full_name"),
                        username=profile.get("username"),
                        avatar_url=profile.get("avatar_url"),
                        invited_by=item.get("invited_by"),
                        created_at=item.get("created_at"),
                    ),
                )
        return GroupResponse(
            id=str(raw.get("id", "")),
            name=str(raw.get("name", "")),
            type=GroupType(raw.get("type") or GroupType.GROUP.value),
            description=raw.get("description"),
            owner_id=str(raw.get("owner_id", "")),
            created_by=raw.get("created_by"),
            updated_by=raw.get("updated_by"),
            created_at=raw.get("created_at"),
            updated_at=raw.get("updated_at"),
            members=members,
        )

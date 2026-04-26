from __future__ import annotations

import asyncio
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

    async def list_my_groups(self, *, access_token: str) -> GroupListResponse:
        user_payload = await self._client.get_user(access_token=access_token)
        user_id = str(user_payload["id"])

        memberships_task = self._client.list_user_memberships(
            access_token=access_token,
            user_id=user_id,
        )
        groups_task = self._client.list_groups(access_token=access_token)
        memberships, groups = await asyncio.gather(memberships_task, groups_task)

        roles_by_group: dict[str, str] = {
            str(item.get("group_id")): str(item.get("role"))
            for item in memberships
            if isinstance(item, dict) and item.get("group_id")
        }

        items: list[GroupSummaryResponse] = []
        for raw in groups:
            if not isinstance(raw, dict):
                continue
            group_id = str(raw.get("id", ""))
            role_value = roles_by_group.get(group_id, GroupMemberRole.MEMBER.value)
            items.append(self._map_summary(raw, role_value))
        return GroupListResponse(items=items)

    async def get_group(
        self,
        *,
        access_token: str,
        group_id: str,
    ) -> GroupResponse:
        raw = await self._client.get_group_with_members(
            access_token=access_token,
            group_id=group_id,
        )
        if raw is None:
            raise NotFoundError("Grupo nao encontrado ou voce nao faz parte dele.")
        return self._map_group(raw)

    async def create_group(
        self,
        *,
        access_token: str,
        request: GroupCreateRequest,
    ) -> GroupResponse:
        user_payload = await self._client.get_user(access_token=access_token)
        owner_id = str(user_payload["id"])

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

        return await self.get_group(
            access_token=access_token,
            group_id=str(created["id"]),
        )

    async def update_group(
        self,
        *,
        access_token: str,
        group_id: str,
        request: GroupUpdateRequest,
    ) -> GroupResponse:
        payload = request.model_dump(exclude_unset=True)
        if "type" in payload and isinstance(payload["type"], GroupType):
            payload["type"] = payload["type"].value
        if not payload:
            raise BadRequestError("Informe ao menos um campo para atualizar o grupo.")

        await self._client.update_group(
            access_token=access_token,
            group_id=group_id,
            payload=payload,
        )
        return await self.get_group(access_token=access_token, group_id=group_id)

    async def delete_group(
        self,
        *,
        access_token: str,
        group_id: str,
    ) -> dict[str, Any]:
        await self._client.delete_group(
            access_token=access_token,
            group_id=group_id,
        )
        return {"success": True, "message": "Grupo removido com sucesso."}

    async def add_member(
        self,
        *,
        access_token: str,
        group_id: str,
        request: GroupMemberAddRequest,
    ) -> GroupResponse:
        user_payload = await self._client.get_user(access_token=access_token)
        invited_by = str(user_payload["id"])

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
                "invited_by": invited_by,
            },
        )
        return await self.get_group(
            access_token=access_token,
            group_id=group_id,
        )

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
        return await self.get_group(
            access_token=access_token,
            group_id=group_id,
        )

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

    async def get_my_context(
        self,
        *,
        access_token: str,
    ) -> ProfileContextResponse:
        user_payload = await self._client.get_user(access_token=access_token)
        user_id = str(user_payload["id"])
        profile_payload = await self._client.get_profile(
            access_token=access_token,
            user_id=user_id,
        )
        if not isinstance(profile_payload, dict):
            raise NotFoundError(
                "Perfil ainda nao foi criado. Faca login novamente para inicializa-lo.",
            )

        active_group_id = profile_payload.get("active_group_id")
        groups_response, active_group = await asyncio.gather(
            self.list_my_groups(access_token=access_token),
            self._safe_get_group(
                access_token=access_token,
                group_id=str(active_group_id) if active_group_id else None,
            ),
        )

        active_role: GroupMemberRole | None = None
        if active_group is not None:
            for member in active_group.members:
                if member.profile_id == user_id:
                    active_role = member.role
                    break

        return ProfileContextResponse(
            user_id=user_id,
            profile_id=str(profile_payload.get("id", user_id)),
            email=profile_payload.get("email") or user_payload.get("email"),
            username=profile_payload.get("username"),
            full_name=profile_payload.get("full_name"),
            avatar_url=profile_payload.get("avatar_url"),
            active_group=active_group,
            active_role=active_role,
            groups=groups_response.items,
        )

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

    async def _safe_get_group(
        self,
        *,
        access_token: str,
        group_id: str | None,
    ) -> GroupResponse | None:
        if not group_id:
            return None
        try:
            return await self.get_group(
                access_token=access_token,
                group_id=group_id,
            )
        except NotFoundError:
            return None

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
    def _map_summary(raw: dict[str, Any], role: str) -> GroupSummaryResponse:
        return GroupSummaryResponse(
            id=str(raw.get("id", "")),
            name=str(raw.get("name", "")),
            type=GroupType(raw.get("type") or GroupType.GROUP.value),
            description=raw.get("description"),
            owner_id=str(raw.get("owner_id", "")),
            role=GroupMemberRole(role) if role in {r.value for r in GroupMemberRole} else GroupMemberRole.MEMBER,
            member_count=int(raw.get("member_count") or 0),
        )

    @staticmethod
    def _map_group(raw: dict[str, Any]) -> GroupResponse:
        members_raw = raw.get("members") or raw.get("group_members") or []
        members: list[GroupMemberResponse] = []
        if isinstance(members_raw, list):
            for item in members_raw:
                if not isinstance(item, dict):
                    continue
                profile = item.get("profile") if isinstance(item.get("profile"), dict) else {}
                members.append(
                    GroupMemberResponse(
                        profile_id=str(item.get("profile_id") or profile.get("id") or ""),
                        role=GroupMemberRole(item.get("role") or GroupMemberRole.MEMBER.value),
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
            created_by=str(raw.get("created_by", "")),
            updated_by=raw.get("updated_by"),
            created_at=raw.get("created_at"),
            updated_at=raw.get("updated_at"),
            members=members,
        )

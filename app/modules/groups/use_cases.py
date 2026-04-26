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
    SeedFilipeVictorRequest,
    SeedFilipeVictorResponse,
)


class ManageGroupsUseCase:
    def __init__(self, client: SupabaseClient) -> None:
        self._client = client

    async def list_groups(self) -> GroupListResponse:
        groups = await self._client.list_groups()
        items = [self._map_summary(raw, GroupMemberRole.MEMBER.value) for raw in groups if isinstance(raw, dict)]
        return GroupListResponse(items=items)

    async def get_group(self, *, group_id: str) -> GroupResponse:
        raw = await self._client.get_group_with_members(group_id=group_id)
        if raw is None:
            raise NotFoundError("Grupo nao encontrado.")
        return self._map_group(raw)

    async def create_group(self, *, request: GroupCreateRequest) -> GroupResponse:
        owner_id = request.owner_id
        if not owner_id:
            raise BadRequestError("Informe owner_id para criar um grupo.")

        partner_id: str | None = request.partner_profile_id
        if partner_id is None and request.partner_email:
            partner_id = await self._resolve_profile_id_by_email(email=request.partner_email)
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
        created = await self._client.insert_group(payload=payload)

        if partner_id is not None:
            try:
                await self._client.insert_group_member(
                    payload={
                        "group_id": created["id"],
                        "profile_id": partner_id,
                        "role": GroupMemberRole.MEMBER.value,
                    },
                )
            except ConflictError:
                pass

        return await self.get_group(group_id=str(created["id"]))

    async def update_group(self, *, group_id: str, request: GroupUpdateRequest) -> GroupResponse:
        payload = request.model_dump(exclude_unset=True)
        if "type" in payload and isinstance(payload["type"], GroupType):
            payload["type"] = payload["type"].value
        if not payload:
            raise BadRequestError("Informe ao menos um campo para atualizar o grupo.")

        await self._client.update_group(group_id=group_id, payload=payload)
        return await self.get_group(group_id=group_id)

    async def delete_group(self, *, group_id: str) -> dict[str, Any]:
        await self._client.delete_group(group_id=group_id)
        return {"success": True, "message": "Grupo removido com sucesso."}

    async def add_member(self, *, group_id: str, request: GroupMemberAddRequest) -> GroupResponse:
        profile_id = request.profile_id
        if profile_id is None and request.email:
            profile_id = await self._resolve_profile_id_by_email(email=request.email)
            if profile_id is None:
                raise NotFoundError(
                    f"Nao encontrei um perfil com o email {request.email}.",
                )

        if profile_id is None:
            raise BadRequestError("Informe profile_id ou email do membro a adicionar.")

        await self._client.insert_group_member(
            payload={
                "group_id": group_id,
                "profile_id": profile_id,
                "role": request.role.value,
            },
        )
        return await self.get_group(group_id=group_id)

    async def remove_member(self, *, group_id: str, profile_id: str) -> GroupResponse:
        await self._client.delete_group_member(group_id=group_id, profile_id=profile_id)
        return await self.get_group(group_id=group_id)

    async def seed_filipe_victor(self, *, request: SeedFilipeVictorRequest) -> SeedFilipeVictorResponse:
        result = await self._client.call_rpc(
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

    async def _resolve_profile_id_by_email(self, *, email: str) -> str | None:
        profile = await self._client.find_profile_by_email(email=email)
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
            created_by=raw.get("created_by"),
            updated_by=raw.get("updated_by"),
            created_at=raw.get("created_at"),
            updated_at=raw.get("updated_at"),
            members=members,
        )

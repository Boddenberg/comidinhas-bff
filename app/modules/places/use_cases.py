from __future__ import annotations

from typing import Any

from app.core.errors import BadRequestError, NotFoundError
from app.integrations.supabase.client import SupabaseClient
from app.modules.places.schemas import (
    PlaceCreateRequest,
    PlaceCreatorResponse,
    PlaceListParams,
    PlaceListResponse,
    PlacePhotoResponse,
    PlaceResponse,
    PlaceStatus,
    PlaceUpdateRequest,
)


class ManagePlacesUseCase:
    PLACE_LIST_SELECT = (
        "*,"
        "creator:created_by(id,full_name,username,avatar_url),"
        "last_editor:updated_by(id,full_name,username,avatar_url)"
    )
    PLACE_DETAIL_SELECT = (
        "*,"
        "creator:created_by(id,full_name,username,avatar_url),"
        "last_editor:updated_by(id,full_name,username,avatar_url),"
        "photos:place_photos(id,place_id,group_id,public_url,storage_path,is_cover,sort_order,created_by,created_at)"
    )

    PLACE_SELECT = PLACE_LIST_SELECT  # backward compat

    def __init__(self, client: SupabaseClient) -> None:
        self._client = client

    async def list_places(
        self,
        *,
        access_token: str,
        params: PlaceListParams,
    ) -> PlaceListResponse:
        group_id = await self._resolve_group_id(
            access_token=access_token,
            group_id=params.group_id,
        )

        rows, total = await self._client.list_places(
            access_token=access_token,
            group_id=group_id,
            select=self.PLACE_LIST_SELECT,
            filters=params.to_supabase_filters(),
            sort_field=params.sort_by.value,
            sort_descending=params.sort_order.value == "desc",
            page=params.page,
            page_size=params.page_size,
        )

        items = [self._map_place(row) for row in rows if isinstance(row, dict)]
        has_more = (params.page * params.page_size) < total
        return PlaceListResponse(
            items=items,
            page=params.page,
            page_size=params.page_size,
            total=total,
            has_more=has_more,
        )

    async def get_place(
        self,
        *,
        access_token: str,
        place_id: str,
    ) -> PlaceResponse:
        raw = await self._client.get_place(
            access_token=access_token,
            place_id=place_id,
            select=self.PLACE_DETAIL_SELECT,
        )
        if raw is None:
            raise NotFoundError("Lugar nao encontrado.")
        return self._map_place(raw)

    async def create_place(
        self,
        *,
        access_token: str,
        request: PlaceCreateRequest,
    ) -> PlaceResponse:
        user_payload = await self._client.get_user(access_token=access_token)
        creator_id = str(user_payload["id"])

        group_id = await self._resolve_group_id(
            access_token=access_token,
            group_id=request.group_id,
        )

        payload: dict[str, Any] = request.model_dump(
            exclude={"group_id"},
            exclude_unset=False,
        )
        if isinstance(payload.get("status"), PlaceStatus):
            payload["status"] = payload["status"].value
        payload["group_id"] = group_id
        payload["created_by"] = creator_id

        created = await self._client.insert_place(
            access_token=access_token,
            payload=payload,
        )
        return await self.get_place(
            access_token=access_token,
            place_id=str(created["id"]),
        )

    async def update_place(
        self,
        *,
        access_token: str,
        place_id: str,
        request: PlaceUpdateRequest,
    ) -> PlaceResponse:
        payload = request.model_dump(exclude_unset=True)
        if not payload:
            raise BadRequestError("Informe ao menos um campo para atualizar o lugar.")
        if isinstance(payload.get("status"), PlaceStatus):
            payload["status"] = payload["status"].value

        await self._client.update_place(
            access_token=access_token,
            place_id=place_id,
            payload=payload,
        )
        return await self.get_place(
            access_token=access_token,
            place_id=place_id,
        )

    async def delete_place(
        self,
        *,
        access_token: str,
        place_id: str,
    ) -> dict[str, Any]:
        await self._client.delete_place(
            access_token=access_token,
            place_id=place_id,
        )
        return {"success": True, "message": "Lugar removido com sucesso."}

    async def _resolve_group_id(
        self,
        *,
        access_token: str,
        group_id: str | None,
    ) -> str:
        if group_id:
            return group_id

        user_payload = await self._client.get_user(access_token=access_token)
        profile = await self._client.get_profile(
            access_token=access_token,
            user_id=str(user_payload["id"]),
        )
        if isinstance(profile, dict):
            active_group_id = profile.get("active_group_id")
            if isinstance(active_group_id, str) and active_group_id:
                return active_group_id

        raise BadRequestError(
            "Voce ainda nao tem um grupo ativo. Crie um grupo ou informe group_id.",
        )

    @classmethod
    def _map_place(cls, raw: dict[str, Any]) -> PlaceResponse:
        photos_raw = raw.get("photos") or []
        photos = (
            [cls._map_photo(p) for p in photos_raw if isinstance(p, dict)]
            if isinstance(photos_raw, list)
            else []
        )
        return PlaceResponse(
            id=str(raw.get("id", "")),
            group_id=str(raw.get("group_id", "")),
            name=str(raw.get("name", "")),
            category=raw.get("category"),
            neighborhood=raw.get("neighborhood"),
            city=raw.get("city"),
            price_range=raw.get("price_range"),
            link=raw.get("link"),
            image_url=raw.get("image_url"),
            notes=raw.get("notes"),
            status=PlaceStatus(raw.get("status") or PlaceStatus.QUERO_IR.value),
            is_favorite=bool(raw.get("is_favorite") or False),
            created_by=str(raw.get("created_by", "")),
            updated_by=raw.get("updated_by"),
            created_at=raw.get("created_at"),
            updated_at=raw.get("updated_at"),
            creator=cls._map_creator(raw.get("creator")),
            last_editor=cls._map_creator(raw.get("last_editor")),
            photos=photos,
        )

    @staticmethod
    def _map_photo(raw: dict[str, Any]) -> PlacePhotoResponse:
        return PlacePhotoResponse(
            id=str(raw.get("id", "")),
            place_id=str(raw.get("place_id", "")),
            group_id=str(raw.get("group_id", "")),
            public_url=str(raw.get("public_url", "")),
            storage_path=str(raw.get("storage_path", "")),
            is_cover=bool(raw.get("is_cover") or False),
            sort_order=int(raw.get("sort_order") or 0),
            created_by=str(raw.get("created_by", "")),
            created_at=raw.get("created_at"),
        )

    @staticmethod
    def _map_creator(raw: Any) -> PlaceCreatorResponse | None:
        if not isinstance(raw, dict):
            return None
        return PlaceCreatorResponse(
            id=str(raw.get("id", "")),
            full_name=raw.get("full_name"),
            username=raw.get("username"),
            avatar_url=raw.get("avatar_url"),
        )

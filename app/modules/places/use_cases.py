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

    async def list_places(self, *, params: PlaceListParams) -> PlaceListResponse:
        group_id = self._require_group_id(params.group_id)

        rows, total = await self._client.list_places(
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

    async def get_place(self, *, place_id: str) -> PlaceResponse:
        raw = await self._client.get_place(
            place_id=place_id,
            select=self.PLACE_DETAIL_SELECT,
        )
        if raw is None:
            raise NotFoundError("Lugar nao encontrado.")
        return self._map_place(raw)

    async def create_place(self, *, request: PlaceCreateRequest) -> PlaceResponse:
        group_id = self._require_group_id(request.group_id)

        payload: dict[str, Any] = request.model_dump(
            exclude={"group_id"},
            exclude_unset=False,
        )
        if isinstance(payload.get("status"), PlaceStatus):
            payload["status"] = payload["status"].value
        payload["group_id"] = group_id

        created = await self._client.insert_place(payload=payload)
        return await self.get_place(place_id=str(created["id"]))

    async def update_place(
        self,
        *,
        place_id: str,
        request: PlaceUpdateRequest,
    ) -> PlaceResponse:
        payload = request.model_dump(exclude_unset=True)
        if not payload:
            raise BadRequestError("Informe ao menos um campo para atualizar o lugar.")
        if isinstance(payload.get("status"), PlaceStatus):
            payload["status"] = payload["status"].value

        await self._client.update_place(place_id=place_id, payload=payload)
        return await self.get_place(place_id=place_id)

    async def delete_place(self, *, place_id: str) -> dict[str, Any]:
        await self._client.delete_place(place_id=place_id)
        return {"success": True, "message": "Lugar removido com sucesso."}

    @staticmethod
    def _require_group_id(group_id: str | None) -> str:
        if group_id:
            return group_id
        raise BadRequestError("Informe o group_id.")

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
            created_by=raw.get("created_by"),
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
            created_by=raw.get("created_by"),
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

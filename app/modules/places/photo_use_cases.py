from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from fastapi import UploadFile

from app.core.errors import BadRequestError, NotFoundError
from app.integrations.supabase.client import SupabaseClient
from app.modules.places.schemas import PlacePhotoResponse, ReorderPhotosRequest


class ManagePlacePhotosUseCase:
    ALLOWED_IMAGE_TYPES = {
        "image/gif": "gif",
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }

    def __init__(self, client: SupabaseClient) -> None:
        self._client = client

    async def list_photos(
        self,
        *,
        access_token: str,
        place_id: str,
    ) -> list[PlacePhotoResponse]:
        rows = await self._client.list_place_photos(
            access_token=access_token,
            place_id=place_id,
        )
        return [self._map_photo(row) for row in rows if isinstance(row, dict)]

    async def upload_photo(
        self,
        *,
        access_token: str,
        place_id: str,
        file: UploadFile,
        set_as_cover: bool = False,
    ) -> PlacePhotoResponse:
        content_type = file.content_type or ""
        extension = self.ALLOWED_IMAGE_TYPES.get(content_type)
        if extension is None:
            raise BadRequestError(
                "Envie uma imagem JPG, PNG, WEBP ou GIF para o lugar.",
            )

        content = await file.read()
        if not content:
            raise BadRequestError("O arquivo enviado esta vazio.")

        if len(content) > self._client.max_place_photo_bytes:
            raise BadRequestError(
                f"A foto excede o limite de {self._client.max_place_photo_bytes} bytes.",
            )

        count = await self._client.count_place_photos(
            access_token=access_token,
            place_id=place_id,
        )
        if count >= self._client.place_photos_max_per_place:
            raise BadRequestError(
                f"Limite de {self._client.place_photos_max_per_place} fotos por lugar atingido.",
            )

        user_payload = await self._client.get_user(access_token=access_token)
        creator_id = str(user_payload["id"])

        place_data = await self._require_place(access_token=access_token, place_id=place_id)
        group_id = str(place_data.get("group_id", ""))

        object_path = f"{group_id}/{place_id}/{uuid4().hex}.{extension}"
        upload = await self._client.upload_place_photo(
            access_token=access_token,
            object_path=object_path,
            content=content,
            filename=file.filename or f"photo.{extension}",
            content_type=content_type,
        )

        is_first = count == 0
        is_cover = set_as_cover or is_first

        if is_cover:
            await self._client.clear_place_cover_photos(
                access_token=access_token,
                place_id=place_id,
            )

        row = await self._client.insert_place_photo(
            access_token=access_token,
            payload={
                "place_id": place_id,
                "group_id": group_id,
                "storage_path": upload["path"],
                "public_url": upload["public_url"],
                "is_cover": is_cover,
                "sort_order": count,
                "created_by": creator_id,
            },
        )

        if is_cover:
            await self._client.update_place(
                access_token=access_token,
                place_id=place_id,
                payload={"image_url": upload["public_url"]},
            )

        return self._map_photo(row)

    async def set_cover(
        self,
        *,
        access_token: str,
        place_id: str,
        photo_id: str,
    ) -> PlacePhotoResponse:
        photos = await self._client.list_place_photos(
            access_token=access_token,
            place_id=place_id,
        )
        target = next(
            (p for p in photos if isinstance(p, dict) and str(p.get("id")) == photo_id),
            None,
        )
        if target is None:
            raise NotFoundError("Foto nao encontrada neste lugar.")

        await asyncio.gather(
            self._client.clear_place_cover_photos(
                access_token=access_token,
                place_id=place_id,
            ),
            self._client.update_place(
                access_token=access_token,
                place_id=place_id,
                payload={"image_url": target["public_url"]},
            ),
        )
        await self._client.update_place_photo(
            access_token=access_token,
            photo_id=photo_id,
            payload={"is_cover": True},
        )
        target["is_cover"] = True
        return self._map_photo(target)

    async def delete_photo(
        self,
        *,
        access_token: str,
        place_id: str,
        photo_id: str,
    ) -> dict[str, Any]:
        photos = await self._client.list_place_photos(
            access_token=access_token,
            place_id=place_id,
        )
        target = next(
            (p for p in photos if isinstance(p, dict) and str(p.get("id")) == photo_id),
            None,
        )
        if target is None:
            raise NotFoundError("Foto nao encontrada neste lugar.")

        was_cover = bool(target.get("is_cover"))
        storage_path = target.get("storage_path", "")

        await self._client.delete_place_photo_record(
            access_token=access_token,
            photo_id=photo_id,
        )

        if storage_path:
            await self._client.remove_place_photo_from_storage(
                access_token=access_token,
                object_path=storage_path,
            )

        if was_cover:
            remaining = [p for p in photos if isinstance(p, dict) and str(p.get("id")) != photo_id]
            if remaining:
                new_cover = remaining[0]
                await asyncio.gather(
                    self._client.update_place_photo(
                        access_token=access_token,
                        photo_id=str(new_cover["id"]),
                        payload={"is_cover": True},
                    ),
                    self._client.update_place(
                        access_token=access_token,
                        place_id=place_id,
                        payload={"image_url": new_cover["public_url"]},
                    ),
                )
            else:
                await self._client.update_place(
                    access_token=access_token,
                    place_id=place_id,
                    payload={"image_url": None},
                )

        return {"success": True, "message": "Foto removida com sucesso."}

    async def reorder_photos(
        self,
        *,
        access_token: str,
        place_id: str,
        request: ReorderPhotosRequest,
    ) -> list[PlacePhotoResponse]:
        photos = await self._client.list_place_photos(
            access_token=access_token,
            place_id=place_id,
        )
        existing_ids = {str(p["id"]) for p in photos if isinstance(p, dict)}

        for photo_id in request.photo_ids:
            if photo_id not in existing_ids:
                raise BadRequestError(
                    f"Foto {photo_id!r} nao pertence a este lugar.",
                )

        await asyncio.gather(
            *(
                self._client.update_place_photo(
                    access_token=access_token,
                    photo_id=photo_id,
                    payload={"sort_order": idx},
                )
                for idx, photo_id in enumerate(request.photo_ids)
            )
        )

        return await self.list_photos(access_token=access_token, place_id=place_id)

    async def _require_place(
        self,
        *,
        access_token: str,
        place_id: str,
    ) -> dict[str, Any]:
        place = await self._client.get_place(
            access_token=access_token,
            place_id=place_id,
            select="id,group_id,image_url",
        )
        if place is None:
            raise NotFoundError("Lugar nao encontrado.")
        return place

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

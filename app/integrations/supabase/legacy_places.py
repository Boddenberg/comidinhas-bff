from __future__ import annotations

import logging
import time
from typing import Any, Mapping, Sequence
from urllib.parse import quote, urlparse

import httpx

from app.core.config import Settings
from app.core.errors import (
    AuthenticationError,
    BadRequestError,
    ConfigurationError,
    ConflictError,
    ExternalServiceError,
    NotFoundError,
)
from app.core.logging import sanitize_params

logger = logging.getLogger(__name__)

class SupabaseLegacyPlacesMixin:
    async def list_places(
        self,
        *,
        access_token: str | None = None,
        group_id: str,
        select: str,
        filters: list[tuple[str, str]],
        sort_field: str,
        sort_descending: bool,
        page: int,
        page_size: int,
    ) -> tuple[list[Any], int]:
        range_start = (page - 1) * page_size
        range_end = range_start + page_size - 1
        order_suffix = "desc" if sort_descending else "asc"

        params: list[tuple[str, str]] = [
            ("group_id", f"eq.{group_id}"),
            ("select", select),
            ("order", f"{sort_field}.{order_suffix}"),
        ]
        params.extend(filters)

        response = await self._request(
            "GET",
            self._build_url("rest", "places"),
            headers={
                **self._headers(access_token=access_token),
                "Prefer": "count=exact",
                "Range-Unit": "items",
                "Range": f"{range_start}-{range_end}",
            },
            params=params,
            context="places_list",
        )

        total = self._parse_content_range_total(
            response.headers.get("content-range", ""),
        )
        try:
            rows = response.json() if response.content else []
        except ValueError:
            rows = []
        if not isinstance(rows, list):
            raise ExternalServiceError("supabase", "Resposta invalida ao listar lugares.")
        return rows, total

    async def get_place(
        self,
        *,
        access_token: str | None = None,
        place_id: str,
        select: str,
    ) -> dict[str, Any] | None:
        payload = await self._request_json(
            "GET",
            self._build_url("rest", "places"),
            headers=self._headers(access_token=access_token),
            params=[
                ("id", f"eq.{place_id}"),
                ("select", select),
            ],
            context="places_get",
        )
        if not isinstance(payload, list):
            raise ExternalServiceError("supabase", "Resposta invalida ao buscar lugar.")
        first = payload[0] if payload else None
        return first if isinstance(first, dict) else None

    async def insert_place(
        self,
        *,
        access_token: str | None = None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        response = await self._request_json(
            "POST",
            self._build_url("rest", "places"),
            headers={
                **self._headers(access_token=access_token),
                "Prefer": "return=representation",
            },
            json=payload,
            context="places_insert",
        )
        if not isinstance(response, list) or not response or not isinstance(response[0], dict):
            raise ExternalServiceError("supabase", "O Supabase nao retornou o lugar apos a insercao.")
        return response[0]

    async def update_place(
        self,
        *,
        access_token: str | None = None,
        place_id: str,
        payload: dict[str, Any],
    ) -> None:
        await self._request(
            "PATCH",
            self._build_url("rest", "places"),
            headers=self._headers(access_token=access_token),
            params=[("id", f"eq.{place_id}")],
            json=payload,
            context="places_update",
        )

    async def delete_place(
        self,
        *,
        access_token: str | None = None,
        place_id: str,
    ) -> None:
        await self._request(
            "DELETE",
            self._build_url("rest", "places"),
            headers=self._headers(access_token=access_token),
            params=[("id", f"eq.{place_id}")],
            context="places_delete",
        )

    @property
    def max_place_photo_bytes(self) -> int:
        return self._settings.supabase_place_photo_max_bytes

    @property
    def place_photos_max_per_place(self) -> int:
        return self._settings.supabase_place_photos_max_per_place

    async def list_place_photos(
        self,
        *,
        access_token: str | None = None,
        place_id: str,
    ) -> list[Any]:
        payload = await self._request_json(
            "GET",
            self._build_url("rest", "place_photos"),
            headers=self._headers(access_token=access_token),
            params=[
                ("place_id", f"eq.{place_id}"),
                ("select", "*"),
                ("order", "sort_order.asc,created_at.asc"),
            ],
            context="place_photos_list",
        )
        if not isinstance(payload, list):
            raise ExternalServiceError("supabase", "Resposta invalida ao listar fotos do lugar.")
        return payload

    async def insert_place_photo(
        self,
        *,
        access_token: str | None = None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        response = await self._request_json(
            "POST",
            self._build_url("rest", "place_photos"),
            headers={
                **self._headers(access_token=access_token),
                "Prefer": "return=representation",
            },
            json=payload,
            context="place_photos_insert",
        )
        if not isinstance(response, list) or not response or not isinstance(response[0], dict):
            raise ExternalServiceError("supabase", "O Supabase nao retornou a foto apos a insercao.")
        return response[0]

    async def update_place_photo(
        self,
        *,
        access_token: str | None = None,
        photo_id: str,
        payload: dict[str, Any],
    ) -> None:
        await self._request(
            "PATCH",
            self._build_url("rest", "place_photos"),
            headers=self._headers(access_token=access_token),
            params=[("id", f"eq.{photo_id}")],
            json=payload,
            context="place_photos_update",
        )

    async def clear_place_cover_photos(
        self,
        *,
        access_token: str | None = None,
        place_id: str,
    ) -> None:
        await self._request(
            "PATCH",
            self._build_url("rest", "place_photos"),
            headers=self._headers(access_token=access_token),
            params=[("place_id", f"eq.{place_id}"), ("is_cover", "eq.true")],
            json={"is_cover": False},
            context="place_photos_clear_cover",
        )

    async def delete_place_photo_record(
        self,
        *,
        access_token: str | None = None,
        photo_id: str,
    ) -> dict[str, Any] | None:
        payload = await self._request_json(
            "DELETE",
            self._build_url("rest", "place_photos"),
            headers={
                **self._headers(access_token=access_token),
                "Prefer": "return=representation",
            },
            params=[("id", f"eq.{photo_id}")],
            context="place_photos_delete",
        )
        if not isinstance(payload, list):
            return None
        first = payload[0] if payload else None
        return first if isinstance(first, dict) else None

    async def upload_place_photo(
        self,
        *,
        access_token: str | None = None,
        object_path: str,
        content: bytes,
        filename: str,
        content_type: str,
    ) -> dict[str, str]:
        encoded_path = "/".join(quote(part, safe="") for part in object_path.split("/"))
        await self._request(
            "POST",
            self._build_url(
                "storage",
                "object",
                self._settings.supabase_place_photos_bucket,
                encoded_path,
            ),
            headers=self._headers(access_token=access_token, include_content_type=False),
            files={"file": (filename, content, content_type)},
            data={"cacheControl": "3600"},
            context="storage_upload_place_photo",
        )
        return {
            "path": object_path,
            "public_url": self.get_public_place_photo_url(object_path),
        }

    async def remove_place_photo_from_storage(
        self,
        *,
        access_token: str | None = None,
        object_path: str,
    ) -> None:
        try:
            await self._request(
                "DELETE",
                self._build_url("storage", "object", self._settings.supabase_place_photos_bucket),
                headers=self._headers(access_token=access_token),
                json={"prefixes": [object_path]},
                context="storage_remove_place_photo",
            )
        except ExternalServiceError:
            pass

    async def count_place_photos(
        self,
        *,
        access_token: str | None = None,
        place_id: str,
    ) -> int:
        response = await self._request(
            "GET",
            self._build_url("rest", "place_photos"),
            headers={
                **self._headers(access_token=access_token),
                "Prefer": "count=exact",
            },
            params=[
                ("place_id", f"eq.{place_id}"),
                ("select", "id"),
            ],
            context="place_photos_count",
        )
        return self._parse_content_range_total(response.headers.get("content-range", ""))

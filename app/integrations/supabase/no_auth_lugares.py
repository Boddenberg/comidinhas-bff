from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

from app.core.errors import ExternalServiceError

logger = logging.getLogger(__name__)

class SupabaseNoAuthLugaresMixin:
    @property
    def max_lugar_foto_bytes(self) -> int:
        return self._settings.supabase_lugar_foto_max_bytes

    @property
    def max_fotos_por_lugar(self) -> int:
        return self._settings.supabase_lugar_fotos_max_por_lugar

    async def list_lugares(
        self,
        *,
        grupo_id: str,
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
            ("grupo_id", f"eq.{grupo_id}"),
            ("select", select),
            ("order", f"{sort_field}.{order_suffix}"),
        ]
        params.extend(filters)

        response = await self._request(
            "GET",
            self._build_url("rest", "lugares"),
            headers={
                **self._headers(),
                "Prefer": "count=exact",
                "Range-Unit": "items",
                "Range": f"{range_start}-{range_end}",
            },
            params=params,
            context="lugares_list",
        )
        total = self._parse_content_range_total(response.headers.get("content-range", ""))
        try:
            rows = response.json() if response.content else []
        except ValueError:
            rows = []
        if not isinstance(rows, list):
            raise ExternalServiceError("supabase", "Resposta inválida ao listar lugares.")
        return rows, total

    async def get_lugar(self, *, lugar_id: str, select: str = "*") -> dict[str, Any] | None:
        payload = await self._request_json(
            "GET",
            self._build_url("rest", "lugares"),
            headers=self._headers(),
            params=[("id", f"eq.{lugar_id}"), ("select", select)],
            context="lugares_get",
        )
        if not isinstance(payload, list):
            raise ExternalServiceError("supabase", "Resposta inválida ao buscar lugar.")
        first = payload[0] if payload else None
        return first if isinstance(first, dict) else None

    async def insert_lugar(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._request_json(
            "POST",
            self._build_url("rest", "lugares"),
            headers={**self._headers(), "Prefer": "return=representation"},
            json=payload,
            context="lugares_insert",
        )
        if not isinstance(response, list) or not response or not isinstance(response[0], dict):
            raise ExternalServiceError("supabase", "Supabase não retornou o lugar após inserção.")
        return response[0]

    async def update_lugar(self, *, lugar_id: str, payload: dict[str, Any]) -> None:
        await self._request(
            "PATCH",
            self._build_url("rest", "lugares"),
            headers=self._headers(),
            params=[("id", f"eq.{lugar_id}")],
            json=payload,
            context="lugares_update",
        )

    async def delete_lugar(self, *, lugar_id: str) -> None:
        await self._request(
            "DELETE",
            self._build_url("rest", "lugares"),
            headers=self._headers(),
            params=[("id", f"eq.{lugar_id}")],
            json=None,
            context="lugares_delete",
        )

    async def upload_lugar_foto(
        self,
        *,
        object_path: str,
        content: bytes,
        filename: str,
        content_type: str,
    ) -> dict[str, str]:
        from urllib.parse import quote
        encoded_path = "/".join(quote(part, safe="") for part in object_path.split("/"))
        await self._request(
            "POST",
            self._build_url("storage", "object", self._settings.supabase_lugar_fotos_bucket, encoded_path),
            headers=self._headers(include_content_type=False),
            files={"file": (filename, content, content_type)},
            data={"cacheControl": "3600"},
            context="storage_upload_lugar_foto",
        )
        return {
            "path": object_path,
            "public_url": self._build_url(
                "storage", "object", "public",
                self._settings.supabase_lugar_fotos_bucket, object_path,
            ),
        }

    async def remove_lugar_foto(self, *, object_path: str) -> None:
        try:
            await self._request(
                "DELETE",
                self._build_url("storage", "object", self._settings.supabase_lugar_fotos_bucket),
                headers=self._headers(),
                json={"prefixes": [object_path]},
                context="storage_remove_lugar_foto",
            )
        except ExternalServiceError:
            pass

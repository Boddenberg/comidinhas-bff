from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

from app.core.errors import ExternalServiceError

logger = logging.getLogger(__name__)

class SupabaseNoAuthGuiasMixin:
    async def list_guias(self, *, grupo_id: str) -> list[Any]:
        payload = await self._request_json(
            "GET",
            self._build_url("rest", "guias"),
            headers=self._headers(),
            params=[
                ("grupo_id", f"eq.{grupo_id}"),
                ("select", "*"),
                ("order", "criado_em.desc"),
            ],
            context="guias_list",
        )
        if not isinstance(payload, list):
            raise ExternalServiceError("supabase", "Resposta invalida ao listar guias.")
        return payload

    async def get_guia(self, *, guia_id: str) -> dict[str, Any] | None:
        payload = await self._request_json(
            "GET",
            self._build_url("rest", "guias"),
            headers=self._headers(),
            params=[("id", f"eq.{guia_id}"), ("select", "*")],
            context="guias_get",
        )
        if not isinstance(payload, list):
            raise ExternalServiceError("supabase", "Resposta invalida ao buscar guia.")
        first = payload[0] if payload else None
        return first if isinstance(first, dict) else None

    async def insert_guia(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._request_json(
            "POST",
            self._build_url("rest", "guias"),
            headers={**self._headers(), "Prefer": "return=representation"},
            json=payload,
            context="guias_insert",
        )
        if not isinstance(response, list) or not response or not isinstance(response[0], dict):
            raise ExternalServiceError("supabase", "Supabase nao retornou o guia apos insercao.")
        return response[0]

    async def update_guia(self, *, guia_id: str, payload: dict[str, Any]) -> None:
        await self._request(
            "PATCH",
            self._build_url("rest", "guias"),
            headers=self._headers(),
            params=[("id", f"eq.{guia_id}")],
            json=payload,
            context="guias_update",
        )

    async def delete_guia(self, *, guia_id: str) -> None:
        await self._request(
            "DELETE",
            self._build_url("rest", "guias"),
            headers=self._headers(),
            params=[("id", f"eq.{guia_id}")],
            json=None,
            context="guias_delete",
        )

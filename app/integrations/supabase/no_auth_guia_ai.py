from __future__ import annotations

import logging
from typing import Any

from app.core.errors import ExternalServiceError

logger = logging.getLogger(__name__)


class SupabaseNoAuthGuiaAiMixin:
    # ----------------------------------------------------------- jobs
    async def insert_guia_ai_job(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._request_json(
            "POST",
            self._build_url("rest", "guia_ai_jobs"),
            headers={**self._headers(), "Prefer": "return=representation"},
            json=payload,
            context="guia_ai_jobs_insert",
        )
        if not isinstance(response, list) or not response or not isinstance(response[0], dict):
            raise ExternalServiceError(
                "supabase",
                "Supabase nao retornou o job de importacao apos insercao.",
            )
        return response[0]

    async def get_guia_ai_job(self, *, job_id: str) -> dict[str, Any] | None:
        payload = await self._request_json(
            "GET",
            self._build_url("rest", "guia_ai_jobs"),
            headers=self._headers(),
            params=[("id", f"eq.{job_id}"), ("select", "*")],
            context="guia_ai_jobs_get",
        )
        if not isinstance(payload, list):
            raise ExternalServiceError("supabase", "Resposta invalida ao buscar job de importacao.")
        first = payload[0] if payload else None
        return first if isinstance(first, dict) else None

    async def list_guia_ai_jobs(
        self,
        *,
        grupo_id: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        payload = await self._request_json(
            "GET",
            self._build_url("rest", "guia_ai_jobs"),
            headers=self._headers(),
            params=[
                ("grupo_id", f"eq.{grupo_id}"),
                ("select", "*"),
                ("order", "criado_em.desc"),
                ("limit", str(int(limit))),
            ],
            context="guia_ai_jobs_list",
        )
        if not isinstance(payload, list):
            raise ExternalServiceError("supabase", "Resposta invalida ao listar jobs de importacao.")
        return [item for item in payload if isinstance(item, dict)]

    async def update_guia_ai_job(self, *, job_id: str, payload: dict[str, Any]) -> None:
        if not payload:
            return
        await self._request(
            "PATCH",
            self._build_url("rest", "guia_ai_jobs"),
            headers=self._headers(),
            params=[("id", f"eq.{job_id}")],
            json=payload,
            context="guia_ai_jobs_update",
        )

    async def count_active_guia_ai_jobs(
        self,
        *,
        grupo_id: str | None = None,
        perfil_id: str | None = None,
    ) -> int:
        params: list[tuple[str, str]] = [
            ("status", "not.in.(completed,completed_with_warnings,invalid_content,failed,cancelled)"),
            ("select", "id"),
        ]
        if grupo_id:
            params.insert(0, ("grupo_id", f"eq.{grupo_id}"))
        if perfil_id:
            params.insert(0, ("perfil_id", f"eq.{perfil_id}"))
        response = await self._request(
            "GET",
            self._build_url("rest", "guia_ai_jobs"),
            headers={
                **self._headers(),
                "Prefer": "count=exact",
                "Range-Unit": "items",
                "Range": "0-0",
            },
            params=params,
            context="guia_ai_jobs_count_active",
        )
        return self._parse_content_range_total(response.headers.get("content-range", ""))

    async def list_stale_active_jobs(self, *, threshold_iso: str) -> list[dict[str, Any]]:
        payload = await self._request_json(
            "GET",
            self._build_url("rest", "guia_ai_jobs"),
            headers=self._headers(),
            params=[
                ("status", "not.in.(completed,completed_with_warnings,invalid_content,failed,cancelled)"),
                ("atualizado_em", f"lt.{threshold_iso}"),
                ("select", "id,grupo_id,status,atualizado_em"),
                ("order", "atualizado_em.asc"),
                ("limit", "100"),
            ],
            context="guia_ai_jobs_list_stale",
        )
        if not isinstance(payload, list):
            raise ExternalServiceError("supabase", "Resposta invalida ao listar jobs travados.")
        return [item for item in payload if isinstance(item, dict)]

    async def get_guia_ai_job_by_hash(
        self,
        *,
        grupo_id: str,
        texto_hash: str,
    ) -> dict[str, Any] | None:
        payload = await self._request_json(
            "GET",
            self._build_url("rest", "guia_ai_jobs"),
            headers=self._headers(),
            params=[
                ("grupo_id", f"eq.{grupo_id}"),
                ("texto_hash", f"eq.{texto_hash}"),
                ("status", "in.(completed,completed_with_warnings)"),
                ("select", "*"),
                ("order", "criado_em.desc"),
                ("limit", "1"),
            ],
            context="guia_ai_jobs_get_by_hash",
        )
        if not isinstance(payload, list):
            raise ExternalServiceError("supabase", "Resposta invalida ao buscar job por hash.")
        first = payload[0] if payload else None
        return first if isinstance(first, dict) else None

    # ----------------------------------------------------------- itens
    async def insert_guia_itens(
        self,
        *,
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not items:
            return []
        response = await self._request_json(
            "POST",
            self._build_url("rest", "guia_itens"),
            headers={**self._headers(), "Prefer": "return=representation"},
            json=items,
            context="guia_itens_insert",
        )
        if not isinstance(response, list):
            raise ExternalServiceError(
                "supabase",
                "Supabase nao retornou os itens do guia apos insercao.",
            )
        return [item for item in response if isinstance(item, dict)]

    async def list_guia_itens(self, *, guia_id: str) -> list[dict[str, Any]]:
        payload = await self._request_json(
            "GET",
            self._build_url("rest", "guia_itens"),
            headers=self._headers(),
            params=[
                ("guia_id", f"eq.{guia_id}"),
                ("select", "*"),
                ("order", "ordem.asc"),
            ],
            context="guia_itens_list",
        )
        if not isinstance(payload, list):
            raise ExternalServiceError("supabase", "Resposta invalida ao listar itens do guia.")
        return [item for item in payload if isinstance(item, dict)]

    async def get_guia_item(self, *, item_id: str) -> dict[str, Any] | None:
        payload = await self._request_json(
            "GET",
            self._build_url("rest", "guia_itens"),
            headers=self._headers(),
            params=[("id", f"eq.{item_id}"), ("select", "*")],
            context="guia_itens_get",
        )
        if not isinstance(payload, list):
            raise ExternalServiceError("supabase", "Resposta invalida ao buscar item de guia.")
        first = payload[0] if payload else None
        return first if isinstance(first, dict) else None

    async def update_guia_item(self, *, item_id: str, payload: dict[str, Any]) -> None:
        if not payload:
            return
        await self._request(
            "PATCH",
            self._build_url("rest", "guia_itens"),
            headers=self._headers(),
            params=[("id", f"eq.{item_id}")],
            json=payload,
            context="guia_itens_update",
        )

    async def delete_guia_item(self, *, item_id: str) -> None:
        await self._request(
            "DELETE",
            self._build_url("rest", "guia_itens"),
            headers=self._headers(),
            params=[("id", f"eq.{item_id}")],
            json=None,
            context="guia_itens_delete",
        )

    async def delete_guia_itens_by_guia(self, *, guia_id: str) -> None:
        await self._request(
            "DELETE",
            self._build_url("rest", "guia_itens"),
            headers=self._headers(),
            params=[("guia_id", f"eq.{guia_id}")],
            json=None,
            context="guia_itens_delete_by_guia",
        )

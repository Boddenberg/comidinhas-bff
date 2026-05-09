from __future__ import annotations

import logging
from typing import Any

from app.core.errors import ExternalServiceError

logger = logging.getLogger(__name__)


class SupabaseNoAuthSugestoesIaMixin:
    """Acesso a tabela `sugestoes_ia_historico`.

    Mantemos a interface estreita: ler sugestoes recentes do grupo e
    inserir novas em lote. As regras de janela (24h/7d) ficam no caso de
    uso para serem facilmente testaveis sem o Supabase real.
    """

    async def list_sugestoes_ia_recentes(
        self,
        *,
        grupo_id: str,
        since_iso: str,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        params: list[tuple[str, str]] = [
            ("grupo_id", f"eq.{grupo_id}"),
            ("criado_em", f"gte.{since_iso}"),
            ("select", "*"),
            ("order", "criado_em.desc"),
            ("limit", str(max(1, min(limit, 500)))),
        ]
        payload = await self._request_json(
            "GET",
            self._build_url("rest", "sugestoes_ia_historico"),
            headers=self._headers(),
            params=params,
            context="sugestoes_ia_historico_list",
        )
        if not isinstance(payload, list):
            raise ExternalServiceError(
                "supabase", "Resposta invalida ao listar sugestoes da IA."
            )
        return [row for row in payload if isinstance(row, dict)]

    async def insert_sugestoes_ia(
        self, *, rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        if not rows:
            return []
        response = await self._request_json(
            "POST",
            self._build_url("rest", "sugestoes_ia_historico"),
            headers={**self._headers(), "Prefer": "return=representation"},
            json=rows,
            context="sugestoes_ia_historico_insert",
        )
        if not isinstance(response, list):
            raise ExternalServiceError(
                "supabase", "Supabase nao retornou as sugestoes da IA inseridas."
            )
        return [row for row in response if isinstance(row, dict)]

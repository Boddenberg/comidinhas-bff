from __future__ import annotations

from app.core.errors import BadRequestError, ExternalServiceError
from app.integrations.supabase.client import SupabaseClient
from app.modules.home.schemas import HomeResponse, map_home_payload


class GetHomeSummaryUseCase:
    def __init__(self, client: SupabaseClient) -> None:
        self._client = client

    async def get_home(
        self,
        *,
        group_id: str | None = None,
        top_limit: int = 5,
    ) -> HomeResponse:
        if not group_id:
            raise BadRequestError("Informe o group_id.")

        payload = await self._client.call_rpc(
            function_name="home_summary",
            payload={
                "target_group_id": group_id,
                "top_limit": top_limit,
            },
        )

        if not isinstance(payload, dict):
            raise ExternalServiceError(
                "supabase",
                "A funcao home_summary nao retornou um payload valido.",
            )

        return map_home_payload(payload)

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
        access_token: str,
        group_id: str | None = None,
        top_limit: int = 5,
    ) -> HomeResponse:
        target_group_id = await self._resolve_group_id(
            access_token=access_token,
            group_id=group_id,
        )

        payload = await self._client.call_rpc(
            access_token=access_token,
            function_name="home_summary",
            payload={
                "target_group_id": target_group_id,
                "top_limit": top_limit,
            },
        )

        if not isinstance(payload, dict):
            raise ExternalServiceError(
                "supabase",
                "A funcao home_summary nao retornou um payload valido.",
            )

        return map_home_payload(payload)

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
            "Voce ainda nao tem um grupo ativo. Crie um grupo ou informe group_id na home.",
        )

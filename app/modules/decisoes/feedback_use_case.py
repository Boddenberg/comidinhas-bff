from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core.errors import BadRequestError, NotFoundError
from app.integrations.supabase.client import SupabaseClient
from app.modules.decisoes.schemas import (
    SugestaoFeedbackRequest,
    SugestaoFeedbackResponse,
)

logger = logging.getLogger(__name__)


class RegistrarFeedbackSugestaoUseCase:
    """Registra feedback do usuario sobre uma sugestao da IA.

    O endpoint e simples por design: o front passa o id da sugestao
    (que o backend devolveu no historico) junto com `aceito | recusado |
    fui` e um comentario opcional. O use case verifica que a sugestao
    pertence ao grupo informado e atualiza a linha. Esses sinais sao
    usados depois pelo loader de historico para enviesar scoring/prompt.
    """

    def __init__(self, *, supabase_client: SupabaseClient) -> None:
        self._supabase = supabase_client

    async def execute(
        self,
        *,
        sugestao_id: str,
        request: SugestaoFeedbackRequest,
    ) -> SugestaoFeedbackResponse:
        sugestao_id = sugestao_id.strip()
        if not sugestao_id:
            raise BadRequestError("Informe o id da sugestao.")

        atual = await self._supabase.get_sugestao_ia(sugestao_id=sugestao_id)
        if atual is None:
            raise NotFoundError("Sugestao nao encontrada.")

        if str(atual.get("grupo_id", "")) != request.grupo_id:
            raise BadRequestError("A sugestao nao pertence ao grupo informado.")

        feedback_em = datetime.now(timezone.utc).isoformat()
        atualizado = await self._supabase.update_sugestao_ia_feedback(
            sugestao_id=sugestao_id,
            feedback=request.feedback.value,
            comentario=request.comentario,
            feedback_em=feedback_em,
        )
        if atualizado is None:
            atualizado = atual

        logger.info(
            "decisoes.feedback.registrado sugestao_id=%s grupo_id=%s feedback=%s",
            sugestao_id,
            request.grupo_id,
            request.feedback.value,
        )

        return SugestaoFeedbackResponse(
            sugestao_id=sugestao_id,
            grupo_id=request.grupo_id,
            feedback=request.feedback,
            feedback_em=feedback_em,
            comentario=request.comentario,
        )

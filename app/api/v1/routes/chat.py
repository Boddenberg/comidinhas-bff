from fastapi import APIRouter, Depends

from app.api.dependencies import get_chat_use_case
from app.modules.chat.schemas import ChatRequest, ChatResponse
from app.modules.chat.use_cases import ChatWithOpenAIUseCase

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse, summary="Conversa simples com a OpenAI")
async def chat(
    request: ChatRequest,
    use_case: ChatWithOpenAIUseCase = Depends(get_chat_use_case),
) -> ChatResponse:
    return await use_case.execute(request)

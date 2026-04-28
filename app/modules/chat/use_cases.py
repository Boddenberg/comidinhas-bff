import logging

from app.integrations.openai.client import OpenAIClient
from app.modules.chat.schemas import ChatMessage, ChatRequest, ChatResponse

logger = logging.getLogger(__name__)


class ChatWithOpenAIUseCase:
    def __init__(
        self,
        client: OpenAIClient,
        *,
        default_model: str,
        default_system_prompt: str,
    ) -> None:
        self._client = client
        self._default_model = default_model
        self._default_system_prompt = default_system_prompt

    async def execute(self, request: ChatRequest) -> ChatResponse:
        logger.info(
            "chat.execute.start history_messages=%s message_len=%s",
            len(request.history),
            len(request.message),
        )
        conversation = [*request.history, ChatMessage(role="user", content=request.message)]
        transcript = self._build_transcript(conversation)
        reply = await self._client.chat(
            prompt=transcript,
            system_prompt=request.system_prompt or self._default_system_prompt,
            model=self._default_model,
        )
        logger.info("chat.execute.end reply_len=%s model=%s", len(reply), self._default_model)

        return ChatResponse(reply=reply, model=self._default_model)

    def _build_transcript(self, conversation: list[ChatMessage]) -> str:
        lines = [self._format_message(message) for message in conversation]
        lines.append("Assistant:")
        return "\n".join(lines)

    @staticmethod
    def _format_message(message: ChatMessage) -> str:
        role_map = {
            "system": "System",
            "user": "User",
            "assistant": "Assistant",
        }
        return f"{role_map[message.role]}: {message.content}"

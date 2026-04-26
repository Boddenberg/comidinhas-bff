from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ChatRole = Literal["system", "user", "assistant"]


class ChatMessage(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    role: ChatRole
    content: str = Field(..., min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    message: str = Field(..., min_length=1, max_length=4000)
    history: list[ChatMessage] = Field(default_factory=list)
    system_prompt: str | None = Field(default=None, max_length=2000)


class ChatResponse(BaseModel):
    reply: str
    model: str
    provider: str = "openai"

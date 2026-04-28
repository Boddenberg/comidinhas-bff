from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class SendWhatsAppTemplateRequest(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    to: str = Field(..., min_length=8, max_length=20, pattern=r"^\d+$")
    placeholders: list[str] = Field(default_factory=list, max_length=20)
    from_number: str | None = Field(
        default=None,
        alias="from",
        min_length=8,
        max_length=20,
        pattern=r"^\d+$",
    )
    template_name: str | None = Field(
        default=None,
        alias="templateName",
        min_length=1,
        max_length=128,
    )
    language: str | None = Field(default=None, min_length=2, max_length=10)
    message_id: str = Field(
        default_factory=lambda: str(uuid4()),
        alias="messageId",
        min_length=1,
        max_length=100,
    )


class SendWhatsAppTemplateResponse(BaseModel):
    provider: str = "infobip"
    message_id: str
    infobip_response: dict[str, Any] = Field(default_factory=dict)

from app.integrations.infobip.client import InfobipClient
from app.modules.infobip.schemas import (
    SendWhatsAppTemplateRequest,
    SendWhatsAppTemplateResponse,
)


class SendWhatsAppTemplateUseCase:
    def __init__(self, client: InfobipClient) -> None:
        self._client = client

    async def execute(
        self,
        request: SendWhatsAppTemplateRequest,
    ) -> SendWhatsAppTemplateResponse:
        return await self._client.send_whatsapp_template(request)

from fastapi import APIRouter, Depends

from app.api.dependencies import get_send_whatsapp_template_use_case
from app.modules.infobip.schemas import (
    SendWhatsAppTemplateRequest,
    SendWhatsAppTemplateResponse,
)
from app.modules.infobip.use_cases import SendWhatsAppTemplateUseCase

router = APIRouter(prefix="/infobip", tags=["infobip"])


@router.post(
    "/whatsapp/template",
    response_model=SendWhatsAppTemplateResponse,
    summary="Envia template de WhatsApp pela Infobip",
)
async def send_whatsapp_template(
    request: SendWhatsAppTemplateRequest,
    use_case: SendWhatsAppTemplateUseCase = Depends(
        get_send_whatsapp_template_use_case,
    ),
) -> SendWhatsAppTemplateResponse:
    return await use_case.execute(request)

import logging
import time
from typing import Any

import httpx

from app.core.config import Settings
from app.core.errors import ConfigurationError, ExternalServiceError
from app.modules.infobip.schemas import (
    SendWhatsAppTemplateRequest,
    SendWhatsAppTemplateResponse,
)

logger = logging.getLogger(__name__)


class InfobipClient:
    WHATSAPP_TEMPLATE_PATH = "/whatsapp/1/message/template"

    def __init__(self, http_client: httpx.AsyncClient, settings: Settings) -> None:
        self._http_client = http_client
        self._settings = settings

    async def send_whatsapp_template(
        self,
        request: SendWhatsAppTemplateRequest,
    ) -> SendWhatsAppTemplateResponse:
        self._ensure_api_key()

        from_number = request.from_number or self._settings.infobip_whatsapp_from
        if not from_number:
            raise ConfigurationError(
                "Configure INFOBIP_WHATSAPP_FROM no .env ou envie o campo from.",
            )

        template_name = (
            request.template_name
            or self._settings.infobip_default_template_name
            or "test_whatsapp_template_en"
        )
        language = request.language or self._settings.infobip_default_language or "en"
        logger.info(
            "infobip.whatsapp_template.start to=%s template=%s language=%s placeholders=%s",
            request.to,
            template_name,
            language,
            len(request.placeholders),
        )

        payload = {
            "messages": [
                {
                    "from": from_number,
                    "to": request.to,
                    "messageId": request.message_id,
                    "content": {
                        "templateName": template_name,
                        "templateData": {
                            "body": {
                                "placeholders": request.placeholders,
                            }
                        },
                        "language": language,
                    },
                }
            ]
        }

        response_payload = await self._post_json(payload)
        logger.info(
            "infobip.whatsapp_template.end message_id=%s response_keys=%s",
            request.message_id,
            list(response_payload.keys()),
        )
        return SendWhatsAppTemplateResponse(
            message_id=request.message_id,
            infobip_response=response_payload,
        )

    async def _post_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        logger.debug("infobip.request.start path=%s", self.WHATSAPP_TEMPLATE_PATH)
        try:
            response = await self._http_client.post(
                f"{self._settings.infobip_base_url.rstrip('/')}{self.WHATSAPP_TEMPLATE_PATH}",
                headers={
                    "Authorization": self._authorization_header(),
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json=payload,
                timeout=self._settings.infobip_timeout_seconds,
            )
            response.raise_for_status()
            duration_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "infobip.request.end path=%s status=%s duration_ms=%.2f",
                self.WHATSAPP_TEMPLATE_PATH,
                response.status_code,
                duration_ms,
            )
        except httpx.TimeoutException as exc:
            logger.warning("infobip.request.timeout path=%s", self.WHATSAPP_TEMPLATE_PATH)
            raise ExternalServiceError(
                "infobip",
                "Timeout ao chamar a Infobip.",
            ) from exc
        except httpx.HTTPStatusError as exc:
            message = self._extract_error_message(exc.response)
            logger.warning(
                "infobip.request.http_error path=%s status=%s message=%s",
                self.WHATSAPP_TEMPLATE_PATH,
                exc.response.status_code,
                message,
            )
            raise ExternalServiceError(
                "infobip",
                f"Falha ao chamar a Infobip: {message}",
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning("infobip.request.network_error path=%s", self.WHATSAPP_TEMPLATE_PATH)
            raise ExternalServiceError(
                "infobip",
                "Erro de rede ao chamar a Infobip.",
            ) from exc

        try:
            payload = response.json()
        except ValueError:
            return {}

        return payload if isinstance(payload, dict) else {}

    def _ensure_api_key(self) -> None:
        if self._settings.is_infobip_configured:
            return

        raise ConfigurationError(
            "Configure INFOBIP_API_KEY no arquivo .env ou nas variaveis de ambiente.",
        )

    def _authorization_header(self) -> str:
        api_key = self._settings.infobip_api_key or ""
        if api_key.lower().startswith("app "):
            return api_key

        return f"App {api_key}"

    @staticmethod
    def _extract_error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            payload = None

        if isinstance(payload, dict):
            direct_message = InfobipClient._first_string(
                payload,
                ("message", "detail", "description", "text"),
            )
            if direct_message:
                return direct_message

            request_error = payload.get("requestError")
            if isinstance(request_error, dict):
                for value in request_error.values():
                    if isinstance(value, dict):
                        nested_message = InfobipClient._first_string(
                            value,
                            ("message", "detail", "description", "text"),
                        )
                        if nested_message:
                            return nested_message

        return f"HTTP {response.status_code}"

    @staticmethod
    def _first_string(payload: dict[str, Any], keys: tuple[str, ...]) -> str | None:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

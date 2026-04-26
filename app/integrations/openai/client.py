from typing import Any

import httpx

from app.core.config import Settings
from app.core.errors import ConfigurationError, ExternalServiceError


class OpenAIClient:
    def __init__(self, http_client: httpx.AsyncClient, settings: Settings) -> None:
        self._http_client = http_client
        self._settings = settings

    async def chat(
        self,
        *,
        prompt: str,
        system_prompt: str,
        model: str,
    ) -> str:
        self._ensure_api_key()

        response = await self._post_responses(
            payload={
                "model": model,
                "instructions": system_prompt,
                "input": prompt,
            }
        )

        text = self._extract_output_text(response)
        if not text:
            raise ExternalServiceError(
                "openai",
                "A OpenAI retornou uma resposta vazia.",
            )

        return text

    def _ensure_api_key(self) -> None:
        if self._settings.is_openai_configured:
            return

        raise ConfigurationError(
            "Configure OPENAI_API_KEY no arquivo .env ou nas variaveis de ambiente.",
        )

    async def _post_responses(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._http_client.post(
                f"{self._settings.openai_base_url}/responses",
                headers={
                    "Authorization": f"Bearer {self._settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self._settings.openai_timeout_seconds,
            )
            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException as exc:
            raise ExternalServiceError(
                "openai",
                "Timeout ao chamar a OpenAI.",
            ) from exc
        except httpx.HTTPStatusError as exc:
            message = self._extract_error_message(exc.response)
            raise ExternalServiceError(
                "openai",
                f"Falha ao chamar a OpenAI: {message}",
            ) from exc
        except httpx.HTTPError as exc:
            raise ExternalServiceError(
                "openai",
                "Erro de rede ao chamar a OpenAI.",
            ) from exc

    @staticmethod
    def _extract_error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            payload = None

        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                message = error.get("message")
                if isinstance(message, str) and message.strip():
                    return message.strip()

        return f"HTTP {response.status_code}"

    @staticmethod
    def _extract_output_text(payload: dict[str, Any]) -> str:
        direct_output = payload.get("output_text")
        if isinstance(direct_output, str) and direct_output.strip():
            return direct_output.strip()

        output = payload.get("output")
        if not isinstance(output, list):
            return ""

        chunks: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue

            content = item.get("content")
            if not isinstance(content, list):
                continue

            for content_item in content:
                if not isinstance(content_item, dict):
                    continue

                text = content_item.get("text")
                if isinstance(text, str) and text.strip():
                    chunks.append(text.strip())

        return "\n".join(chunks).strip()

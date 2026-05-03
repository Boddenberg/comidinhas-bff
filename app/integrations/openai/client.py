import json
import logging
import time
from typing import Any

import httpx

from app.core.config import Settings
from app.core.errors import ConfigurationError, ExternalServiceError

logger = logging.getLogger(__name__)


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

    async def chat_json(
        self,
        *,
        prompt: str,
        system_prompt: str,
        model: str,
        schema_name: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        payload, _usage = await self.chat_json_with_usage(
            prompt=prompt,
            system_prompt=system_prompt,
            model=model,
            schema_name=schema_name,
            schema=schema,
        )
        return payload

    async def chat_json_with_usage(
        self,
        *,
        prompt: str,
        system_prompt: str,
        model: str,
        schema_name: str,
        schema: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, int]]:
        """Like `chat_json` but also returns the token usage from the response.

        Used by the AI guide pipeline to populate cost accounting on the job.
        """
        self._ensure_api_key()

        response = await self._post_responses(
            payload={
                "model": model,
                "instructions": system_prompt,
                "input": prompt,
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": schema_name,
                        "schema": schema,
                        "strict": True,
                    }
                },
            }
        )

        text = self._extract_output_text(response)
        if not text:
            raise ExternalServiceError(
                "openai",
                "A OpenAI retornou uma resposta JSON vazia.",
            )

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ExternalServiceError(
                "openai",
                "A OpenAI retornou uma resposta que nao e JSON valido.",
            ) from exc

        if not isinstance(payload, dict):
            raise ExternalServiceError(
                "openai",
                "A OpenAI retornou um JSON inesperado.",
            )

        return payload, self._extract_usage(response)

    @staticmethod
    def _extract_usage(response: dict[str, Any]) -> dict[str, int]:
        usage = response.get("usage")
        if not isinstance(usage, dict):
            return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        input_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
        total = int(usage.get("total_tokens") or (input_tokens + output_tokens))
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total,
        }

    def _ensure_api_key(self) -> None:
        if self._settings.is_openai_configured:
            return

        raise ConfigurationError(
            "Configure OPENAI_API_KEY no arquivo .env ou nas variaveis de ambiente.",
        )

    async def _post_responses(self, payload: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        logger.info(
            "openai.responses.start model=%s input_type=%s",
            payload.get("model"),
            type(payload.get("input")).__name__,
        )
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
            duration_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "openai.responses.end model=%s status=%s duration_ms=%.2f",
                payload.get("model"),
                response.status_code,
                duration_ms,
            )
            return response.json()
        except httpx.TimeoutException as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.warning(
                "openai.responses.timeout model=%s duration_ms=%.2f",
                payload.get("model"),
                duration_ms,
            )
            raise ExternalServiceError(
                "openai",
                "Timeout ao chamar a OpenAI.",
            ) from exc
        except httpx.HTTPStatusError as exc:
            message = self._extract_error_message(exc.response)
            duration_ms = (time.perf_counter() - start) * 1000
            logger.warning(
                "openai.responses.http_error model=%s status=%s duration_ms=%.2f message=%s",
                payload.get("model"),
                exc.response.status_code,
                duration_ms,
                message,
            )
            raise ExternalServiceError(
                "openai",
                f"Falha ao chamar a OpenAI: {message}",
            ) from exc
        except httpx.HTTPError as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.warning(
                "openai.responses.network_error model=%s duration_ms=%.2f",
                payload.get("model"),
                duration_ms,
            )
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

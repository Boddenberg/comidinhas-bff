from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)


# Pricing snapshot (USD por 1M tokens). Apenas para estimativa interna —
# nao ha cobranca, e quando precos mudarem basta ajustar aqui.
# Conservador: usa o teto da familia que esta na config padrao (gpt-4o-mini).
_DEFAULT_USD_PER_1M_INPUT = 0.15
_DEFAULT_USD_PER_1M_OUTPUT = 0.60
_DEFAULT_USD_TO_BRL = 5.30


class CostTracker:
    """Accumulates LLM and Maps usage for a single AI guide job.

    Pure in-memory and per-job: no persistence here. The job runner reads
    the totals at the end and writes them into `estatisticas` on the job row.
    """

    def __init__(
        self,
        *,
        usd_per_1m_input_tokens: float = _DEFAULT_USD_PER_1M_INPUT,
        usd_per_1m_output_tokens: float = _DEFAULT_USD_PER_1M_OUTPUT,
        usd_to_brl: float = _DEFAULT_USD_TO_BRL,
    ) -> None:
        self._lock = threading.Lock()
        self._llm_calls = 0
        self._llm_input_tokens = 0
        self._llm_output_tokens = 0
        self._google_calls = 0
        self._photos_found = 0
        self._usd_per_input = usd_per_1m_input_tokens / 1_000_000.0
        self._usd_per_output = usd_per_1m_output_tokens / 1_000_000.0
        self._usd_to_brl = usd_to_brl

    def record_llm(self, *, input_tokens: int, output_tokens: int) -> None:
        with self._lock:
            self._llm_calls += 1
            self._llm_input_tokens += max(0, int(input_tokens))
            self._llm_output_tokens += max(0, int(output_tokens))

    def record_google_calls(self, n: int) -> None:
        if n <= 0:
            return
        with self._lock:
            self._google_calls += int(n)

    def record_photo(self) -> None:
        with self._lock:
            self._photos_found += 1

    def snapshot(self) -> dict[str, float | int]:
        with self._lock:
            usd_estimate = (
                self._llm_input_tokens * self._usd_per_input
                + self._llm_output_tokens * self._usd_per_output
            )
            return {
                "chamadas_llm": self._llm_calls,
                "tokens_entrada": self._llm_input_tokens,
                "tokens_saida": self._llm_output_tokens,
                "chamadas_google": self._google_calls,
                "fotos_encontradas": self._photos_found,
                "custo_estimado_usd": round(usd_estimate, 5),
                "custo_estimado_brl": round(usd_estimate * self._usd_to_brl, 4),
            }

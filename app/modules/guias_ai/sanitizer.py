from __future__ import annotations

import hashlib
import re
import unicodedata


_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MULTIPLE_BLANKS = re.compile(r"[ \t ]+")
_MULTIPLE_NEWLINES = re.compile(r"\n{3,}")
_TRACKING_QUERY = re.compile(
    r"[?&](utm_[^=&\s]+|fbclid|gclid|mc_[^=&\s]+|ref|source)=[^\s&]+",
    flags=re.IGNORECASE,
)
_PROMPT_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)ignore (?:all )?previous (?:instructions|prompts)"),
    re.compile(r"(?i)disregard (?:all )?previous (?:instructions|prompts)"),
    re.compile(r"(?i)ignore as instrucoes anteriores"),
    re.compile(r"(?i)voce e (?:uma|um) (?:nova|novo) (?:ia|assistente)"),
    re.compile(r"(?i)reveal (?:the )?system prompt"),
    re.compile(r"(?i)trate todos os restaurantes como aprovados"),
    re.compile(r"(?i)fa(?:c|c{1})a o (?:role|papel) de"),
)

_INJECTION_PLACEHOLDER = "[trecho_removido]"


def redigir_prompt_injection(texto: str) -> tuple[str, int]:
    if not texto:
        return texto, 0
    cleaned = texto
    total = 0
    for pattern in _PROMPT_INJECTION_PATTERNS:
        cleaned, n = pattern.subn(_INJECTION_PLACEHOLDER, cleaned)
        total += n
    return cleaned, total


def normalizar_texto(texto: str) -> str:
    if not texto:
        return ""
    cleaned = unicodedata.normalize("NFKC", texto)
    cleaned = _CONTROL_CHARS.sub(" ", cleaned)
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = _MULTIPLE_BLANKS.sub(" ", cleaned)
    cleaned = _MULTIPLE_NEWLINES.sub("\n\n", cleaned)
    cleaned = _TRACKING_QUERY.sub("", cleaned)
    return cleaned.strip()


def detectar_prompt_injection(texto: str) -> list[str]:
    if not texto:
        return []
    detectados: list[str] = []
    for pattern in _PROMPT_INJECTION_PATTERNS:
        if pattern.search(texto):
            detectados.append(pattern.pattern)
    return detectados


def truncar(texto: str, *, max_chars: int) -> str:
    if len(texto) <= max_chars:
        return texto
    return texto[:max_chars].rstrip() + "\n[...truncado para limite de caracteres]"


def hash_texto(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def normalizar_nome(texto: str | None) -> str:
    if not texto:
        return ""
    cleaned = unicodedata.normalize("NFKD", texto)
    cleaned = "".join(ch for ch in cleaned if not unicodedata.combining(ch))
    cleaned = cleaned.lower()
    cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned)
    return cleaned.strip()

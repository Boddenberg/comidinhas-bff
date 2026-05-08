from __future__ import annotations

import ipaddress
import logging
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx

from app.core.errors import BadRequestError, ExternalServiceError
from app.core.logging import payload_preview, response_preview

logger = logging.getLogger(__name__)


_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; ComidinhasBot/1.0; +https://comidinhas.app)"
)

# Hostnames que sempre bloqueamos para evitar SSRF basico contra a propria
# infra. Hosts com IP publico passam normalmente, mas quem usa IP literal
# privado e barrado abaixo via ipaddress.
_BLOCKED_HOSTS = frozenset({"localhost", "0.0.0.0"})

# Tags cujo conteudo nao queremos no texto extraido. Removemos tudo que esta
# dentro delas.
_TAGS_HIDDEN = frozenset(
    {
        "script",
        "style",
        "noscript",
        "template",
        "svg",
        "iframe",
        "form",
        "nav",
        "header",
        "footer",
        "aside",
        "button",
        "input",
        "select",
        "textarea",
        "menu",
    }
)

# Tags em bloco — apos fechar, inserimos uma quebra de linha pra preservar
# minimamente a estrutura do texto (rankings em tabela, listas, etc).
_TAGS_BLOCK = frozenset(
    {
        "p",
        "div",
        "section",
        "article",
        "main",
        "li",
        "ul",
        "ol",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "br",
        "hr",
        "tr",
        "td",
        "th",
        "blockquote",
        "pre",
    }
)


class _TextExtractor(HTMLParser):
    """Extrai texto de HTML preservando uma estrutura minima de paragrafos."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._buffer: list[str] = []
        self._skip_depth = 0
        self.title: str | None = None
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _TAGS_HIDDEN:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
            return
        if tag in {"br", "hr"}:
            self._buffer.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _TAGS_HIDDEN:
            if self._skip_depth > 0:
                self._skip_depth -= 1
            return
        if tag == "title":
            self._in_title = False
            return
        if tag in _TAGS_BLOCK:
            self._buffer.append("\n")

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        if tag in {"br", "hr"}:
            self._buffer.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        if self._in_title:
            self.title = (self.title or "") + data
            return
        self._buffer.append(data)

    @property
    def text(self) -> str:
        raw = "".join(self._buffer)
        # Normaliza espacos: colapsa horizontais, preserva quebras simples.
        raw = re.sub(r"[ \t ]+", " ", raw)
        raw = re.sub(r" *\n *", "\n", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def _is_url_safe(url: str) -> tuple[bool, str | None]:
    """Validates URL scheme/host. Returns (is_safe, motivo_ou_None)."""
    if not url or not isinstance(url, str):
        return False, "URL invalida."
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return False, "URL invalida."
    if parsed.scheme not in ("http", "https"):
        return False, "Use apenas URLs http:// ou https://."
    host = (parsed.hostname or "").lower()
    if not host:
        return False, "URL sem host."
    if host in _BLOCKED_HOSTS or host.endswith(".localhost"):
        return False, "Host nao permitido."
    # Bloqueia IP literal em range privado / loopback / link-local.
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True, None
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
    ):
        return False, "IP privado nao permitido."
    return True, None


async def fetch_url_as_text(
    url: str,
    *,
    timeout_seconds: float = 20.0,
    max_bytes: int = 5_000_000,
    max_redirects: int = 5,
    http_client: httpx.AsyncClient | None = None,
) -> dict:
    """Baixa a URL e retorna texto + metadados.

    Returns:
        ``{"texto": str, "titulo": str | None, "url_final": str}``

    Raises:
        BadRequestError: URL invalida ou bloqueada.
        ExternalServiceError: falha de rede / status >= 400.
    """
    safe, motivo = _is_url_safe(url)
    if not safe:
        raise BadRequestError(motivo or "URL invalida.")

    headers = {
        "User-Agent": _DEFAULT_USER_AGENT,
        "Accept": "text/html,text/plain,application/xhtml+xml,*/*;q=0.5",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    }
    timeout = httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 10.0))
    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        max_redirects=max_redirects,
    )
    logger.info(
        "guias_ai.url_fetcher.request.start url=%s headers=%s",
        url,
        payload_preview(headers, max_chars=1000),
    )
    try:
        try:
            response = await client.get(url, headers=headers)
        except httpx.TimeoutException as exc:
            raise ExternalServiceError(
                "url_fetcher",
                "Tempo esgotado ao baixar a pagina.",
                status_code=504,
            ) from exc
        except httpx.HTTPError as exc:
            raise ExternalServiceError(
                "url_fetcher",
                f"Falha ao baixar a pagina: {type(exc).__name__}.",
                status_code=502,
            ) from exc
    finally:
        if owns_client:
            await client.aclose()

    logger.info(
        "guias_ai.url_fetcher.request.end url=%s final_url=%s status=%s response=%s",
        url,
        str(response.url),
        response.status_code,
        response_preview(response, max_chars=4000),
    )
    if response.status_code >= 400:
        raise ExternalServiceError(
            "url_fetcher",
            f"A pagina respondeu com erro HTTP {response.status_code}.",
            status_code=502,
        )

    raw_bytes = response.content or b""
    truncated = False
    if len(raw_bytes) > max_bytes:
        raw_bytes = raw_bytes[:max_bytes]
        truncated = True
        logger.info(
            "guias_ai.url_fetcher.truncated url=%s tamanho=%s max=%s",
            url,
            len(response.content),
            max_bytes,
        )

    encoding = response.encoding or "utf-8"
    try:
        body_text = raw_bytes.decode(encoding, errors="replace")
    except (LookupError, AttributeError):
        body_text = raw_bytes.decode("utf-8", errors="replace")

    content_type = response.headers.get("content-type", "").lower()
    final_url = str(response.url)

    if "text/plain" in content_type:
        cleaned = re.sub(r"\r\n?", "\n", body_text)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        logger.info(
            "guias_ai.url_fetcher.fetched url=%s tipo=text/plain bytes=%s "
            "tamanho_texto=%s truncado=%s",
            url,
            len(raw_bytes),
            len(cleaned),
            truncated,
        )
        return {"texto": cleaned, "titulo": None, "url_final": final_url}

    parser = _TextExtractor()
    try:
        parser.feed(body_text)
        parser.close()
    except Exception:
        logger.exception("guias_ai.url_fetcher.parse_failed url=%s", url)
        # Fallback bem permissivo: tira tags via regex.
        fallback = re.sub(r"<[^>]+>", " ", body_text)
        fallback = re.sub(r"\s+", " ", fallback).strip()
        return {"texto": fallback, "titulo": None, "url_final": final_url}

    titulo = (parser.title or "").strip() or None
    if titulo:
        titulo = re.sub(r"\s+", " ", titulo)[:200]

    texto_extraido = parser.text
    logger.info(
        "guias_ai.url_fetcher.fetched url=%s tipo=html bytes=%s "
        "tamanho_texto=%s titulo=%s truncado=%s",
        url,
        len(raw_bytes),
        len(texto_extraido),
        bool(titulo),
        truncated,
    )
    return {
        "texto": texto_extraido,
        "titulo": titulo,
        "url_final": final_url,
    }

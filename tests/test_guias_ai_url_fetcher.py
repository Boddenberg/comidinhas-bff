import httpx
import pytest

from app.core.errors import BadRequestError, ExternalServiceError
from app.modules.guias_ai.url_fetcher import _is_url_safe, fetch_url_as_text


def test_url_safe_accepts_https() -> None:
    safe, motivo = _is_url_safe("https://exemplo.com/post")
    assert safe is True
    assert motivo is None


def test_url_safe_rejects_localhost() -> None:
    safe, motivo = _is_url_safe("http://localhost:8000/admin")
    assert safe is False
    assert motivo


def test_url_safe_rejects_private_ip() -> None:
    safe, _ = _is_url_safe("http://10.0.0.1/")
    assert safe is False
    safe, _ = _is_url_safe("http://192.168.1.10/")
    assert safe is False
    safe, _ = _is_url_safe("http://127.0.0.1/")
    assert safe is False


def test_url_safe_rejects_non_http_scheme() -> None:
    safe, motivo = _is_url_safe("ftp://exemplo.com/file")
    assert safe is False
    assert "http" in (motivo or "").lower()


def test_url_safe_rejects_missing_host() -> None:
    safe, _ = _is_url_safe("http:///abc")
    assert safe is False


@pytest.mark.anyio
async def test_fetch_extracts_text_and_title_from_html() -> None:
    html = (
        "<html><head><title>Os 5 melhores</title></head>"
        "<body>"
        "<nav>menu</nav>"
        "<header>banner</header>"
        "<main><article>"
        "<h1>Top 5 hamburguerias</h1>"
        "<ol><li>Burger A - Vila Madalena</li>"
        "<li>Burger B - Pinheiros</li></ol>"
        "<script>alert('x')</script>"
        "<style>.x{}</style>"
        "</article></main>"
        "<footer>2026</footer>"
        "</body></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("user-agent", "").startswith("Mozilla/")
        return httpx.Response(
            200,
            content=html.encode("utf-8"),
            headers={"content-type": "text/html; charset=utf-8"},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        resultado = await fetch_url_as_text(
            "https://blog.exemplo.com/top-5", http_client=client
        )

    assert resultado["titulo"] == "Os 5 melhores"
    texto = resultado["texto"]
    assert "Top 5 hamburguerias" in texto
    assert "Burger A" in texto
    assert "Burger B" in texto
    # Limpou ruidos:
    assert "alert" not in texto
    assert ".x{}" not in texto
    assert "menu" not in texto.lower().split("\n")[0]
    assert "2026" not in texto


@pytest.mark.anyio
async def test_fetch_returns_plain_text_as_is() -> None:
    body = "linha 1\nlinha 2\nlinha 3"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=body.encode("utf-8"),
            headers={"content-type": "text/plain; charset=utf-8"},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        resultado = await fetch_url_as_text(
            "https://exemplo.com/raw", http_client=client
        )

    assert resultado["titulo"] is None
    assert "linha 1" in resultado["texto"]
    assert "linha 3" in resultado["texto"]


@pytest.mark.anyio
async def test_fetch_raises_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            content=b"<html><body>nao encontrado</body></html>",
            headers={"content-type": "text/html"},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ExternalServiceError) as exc_info:
            await fetch_url_as_text(
                "https://exemplo.com/quebrado", http_client=client
            )
    assert "404" in str(exc_info.value.message)


@pytest.mark.anyio
async def test_fetch_truncates_oversized_payload() -> None:
    huge = ("<p>linha</p>" * 10_000).encode("utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=huge,
            headers={"content-type": "text/html"},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        resultado = await fetch_url_as_text(
            "https://exemplo.com/grande",
            max_bytes=500,
            http_client=client,
        )

    # Trunca antes do parse, entao o texto nao vai ter os 10_000 paragrafos.
    assert len(resultado["texto"]) < 5_000


@pytest.mark.anyio
async def test_fetch_rejects_invalid_url() -> None:
    with pytest.raises(BadRequestError):
        await fetch_url_as_text("ftp://exemplo.com/x")
    with pytest.raises(BadRequestError):
        await fetch_url_as_text("http://localhost:1234/admin")


@pytest.mark.anyio
async def test_fetch_returns_final_url_after_redirect() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/inicial":
            return httpx.Response(
                301,
                headers={"location": "https://exemplo.com/final"},
            )
        return httpx.Response(
            200,
            content=b"<html><title>Final</title><body>ok</body></html>",
            headers={"content-type": "text/html"},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        transport=transport, follow_redirects=True
    ) as client:
        resultado = await fetch_url_as_text(
            "https://exemplo.com/inicial", http_client=client
        )

    assert resultado["url_final"].endswith("/final")
    assert resultado["titulo"] == "Final"

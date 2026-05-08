import httpx

from app.core.logging import files_preview, payload_preview, response_preview


def test_payload_preview_redacts_sensitive_values() -> None:
    preview = payload_preview(
        {
            "Authorization": "Bearer secret-token",
            "nested": {"api_key": "maps-key", "value": "ok"},
        },
        max_chars=1000,
    )

    assert preview is not None
    assert "secret-token" not in preview
    assert "maps-key" not in preview
    assert '"Authorization": "***"' in preview
    assert '"api_key": "***"' in preview
    assert '"value": "ok"' in preview


def test_response_preview_redacts_json_response_values() -> None:
    response = httpx.Response(
        200,
        json={"access_token": "secret-token", "result": {"id": "place-1"}},
    )

    preview = response_preview(response, max_chars=1000)

    assert preview is not None
    assert "secret-token" not in preview
    assert '"access_token": "***"' in preview
    assert '"id": "place-1"' in preview


def test_files_preview_never_logs_binary_content() -> None:
    preview = files_preview(
        {"file": ("photo.jpg", b"binary-photo-content", "image/jpeg")}
    )

    assert preview == {
        "file": {
            "filename": "photo.jpg",
            "content_type": "image/jpeg",
            "content_length": 20,
        }
    }

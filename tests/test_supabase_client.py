import json

import httpx
import pytest

from app.core.config import Settings
from app.integrations.supabase.client import SupabaseClient


@pytest.mark.anyio
async def test_supabase_client_sign_up_normalizes_auth_payload() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["query"] = request.url.query.decode()
        seen["authorization"] = request.headers.get("Authorization")
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(
            status_code=200,
            json={
                "access_token": "access-token",
                "refresh_token": "refresh-token",
                "token_type": "bearer",
                "expires_in": 3600,
                "user": {
                    "id": "user-123",
                    "email": "ana@example.com",
                    "user_metadata": {"username": "ana.silva"},
                },
            },
        )

    settings = Settings(
        supabase_url="https://project.supabase.co",
        supabase_key="sb_publishable_test",
    )
    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(transport=transport) as http_client:
        client = SupabaseClient(http_client=http_client, settings=settings)
        response = await client.sign_up(
            email="ana@example.com",
            password="segredo123",
            metadata={"username": "ana.silva"},
            email_redirect_to="https://app.example.com/welcome",
        )

    assert seen["path"] == "/auth/v1/signup"
    assert seen["query"] == "redirect_to=https%3A%2F%2Fapp.example.com%2Fwelcome"
    assert seen["authorization"] == "Bearer sb_publishable_test"
    assert seen["body"] == {
        "email": "ana@example.com",
        "password": "segredo123",
        "data": {"username": "ana.silva"},
    }
    assert response["session"]["access_token"] == "access-token"
    assert response["email_confirmation_required"] is False


@pytest.mark.anyio
async def test_supabase_client_upload_profile_photo_builds_public_url() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["authorization"] = request.headers.get("Authorization")
        return httpx.Response(
            status_code=200,
            json={"Key": "profile-photos/user-123/avatar-1.jpg"},
        )

    settings = Settings(
        supabase_url="https://project.supabase.co",
        supabase_key="sb_publishable_test",
        supabase_profile_bucket="profile-photos",
    )
    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(transport=transport) as http_client:
        client = SupabaseClient(http_client=http_client, settings=settings)
        response = await client.upload_profile_photo(
            access_token="access-token",
            object_path="user-123/avatar-1.jpg",
            content=b"fake-image",
            filename="avatar.jpg",
            content_type="image/jpeg",
        )

    assert seen["path"] == "/storage/v1/object/profile-photos/user-123/avatar-1.jpg"
    assert seen["authorization"] == "Bearer access-token"
    assert response["path"] == "user-123/avatar-1.jpg"
    assert (
        response["public_url"]
        == "https://project.supabase.co/storage/v1/object/public/profile-photos/user-123/avatar-1.jpg"
    )

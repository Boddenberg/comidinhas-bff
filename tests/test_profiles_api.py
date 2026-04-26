from fastapi.testclient import TestClient

from app.api.dependencies import get_manage_profiles_use_case
from app.main import app
from app.modules.profiles.schemas import (
    AuthenticatedUserResponse,
    ProfileAuthResponse,
    ProfileMeResponse,
    ProfileResponse,
    ProfileSessionResponse,
)


def build_user() -> AuthenticatedUserResponse:
    return AuthenticatedUserResponse(
        id="user-123",
        email="ana@example.com",
        user_metadata={"username": "ana.silva"},
    )


def build_profile() -> ProfileResponse:
    return ProfileResponse(
        id="user-123",
        email="ana@example.com",
        username="ana.silva",
        full_name="Ana Silva",
        city="Sao Paulo",
    )


class FakeProfilesUseCase:
    async def sign_up(self, request):  # type: ignore[no-untyped-def]
        assert request.username == "ana.silva"
        return ProfileAuthResponse(
            user=build_user(),
            profile=build_profile(),
            session=ProfileSessionResponse(
                access_token="access-token",
                refresh_token="refresh-token",
            ),
        )

    async def get_me(self, *, access_token: str):  # type: ignore[no-untyped-def]
        assert access_token == "access-token"
        return ProfileMeResponse(
            user=build_user(),
            profile=build_profile(),
        )

    async def upload_photo(self, *, access_token: str, file):  # type: ignore[no-untyped-def]
        assert access_token == "access-token"
        assert file.filename == "avatar.png"
        profile = build_profile().model_copy(
            update={
                "avatar_path": "user-123/avatar-1.png",
                "avatar_url": "https://project.supabase.co/storage/v1/object/public/profile-photos/user-123/avatar-1.png",
            }
        )
        return ProfileMeResponse(
            user=build_user(),
            profile=profile,
        )


def test_profiles_signup_route() -> None:
    app.dependency_overrides[get_manage_profiles_use_case] = lambda: FakeProfilesUseCase()

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/profiles/signup",
            json={
                "email": "ana@example.com",
                "password": "segredo123",
                "username": "ana.silva",
                "full_name": "Ana Silva",
                "city": "Sao Paulo",
            },
        )

    app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["profile"]["username"] == "ana.silva"
    assert response.json()["session"]["access_token"] == "access-token"


def test_profiles_me_route() -> None:
    app.dependency_overrides[get_manage_profiles_use_case] = lambda: FakeProfilesUseCase()

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/profiles/me",
            headers={"Authorization": "Bearer access-token"},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["profile"]["full_name"] == "Ana Silva"


def test_profiles_photo_upload_route() -> None:
    app.dependency_overrides[get_manage_profiles_use_case] = lambda: FakeProfilesUseCase()

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/profiles/me/photo",
            headers={"Authorization": "Bearer access-token"},
            files={"file": ("avatar.png", b"fake-image", "image/png")},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["profile"]["avatar_path"] == "user-123/avatar-1.png"


def test_profiles_me_requires_bearer_token() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/profiles/me")

    assert response.status_code == 401
    assert response.json()["code"] == "authentication_error"

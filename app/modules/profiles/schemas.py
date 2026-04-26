from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProfileSessionResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int | None = None
    expires_at: int | None = None


class AuthenticatedUserResponse(BaseModel):
    id: str
    email: str | None = None
    email_confirmed_at: datetime | None = None
    last_sign_in_at: datetime | None = None
    user_metadata: dict[str, Any] = Field(default_factory=dict)


class ProfileResponse(BaseModel):
    id: str
    email: str | None = None
    username: str | None = None
    full_name: str | None = None
    phone: str | None = None
    birth_date: date | None = None
    city: str | None = None
    state: str | None = None
    bio: str | None = None
    favorite_cuisine: str | None = None
    avatar_path: str | None = None
    avatar_url: str | None = None
    preferences: dict[str, Any] = Field(default_factory=dict)
    extra_data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProfileMeResponse(BaseModel):
    user: AuthenticatedUserResponse
    profile: ProfileResponse


class ProfileAuthResponse(BaseModel):
    user: AuthenticatedUserResponse
    profile: ProfileResponse | None = None
    session: ProfileSessionResponse | None = None
    email_confirmation_required: bool = False
    message: str | None = None


class ActionResponse(BaseModel):
    success: bool = True
    message: str


class ProfileFieldsMixin(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    full_name: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=30)
    birth_date: date | None = None
    city: str | None = Field(default=None, max_length=80)
    state: str | None = Field(default=None, max_length=80)
    bio: str | None = Field(default=None, max_length=500)
    favorite_cuisine: str | None = Field(default=None, max_length=80)
    preferences: dict[str, Any] | None = None
    extra_data: dict[str, Any] | None = None


class ProfileSignUpRequest(ProfileFieldsMixin):
    email: str = Field(..., min_length=5, max_length=255)
    password: str = Field(..., min_length=8, max_length=72)
    username: str = Field(..., min_length=3, max_length=30, pattern=r"^[a-zA-Z0-9_.-]+$")

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.strip().lower()


class ProfileSignInRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(..., min_length=5, max_length=255)
    password: str = Field(..., min_length=8, max_length=72)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class ProfileRefreshSessionRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    refresh_token: str = Field(..., min_length=10)


class ProfileSignOutRequest(BaseModel):
    scope: Literal["global", "local", "others"] = "global"


class ProfileUpdateRequest(ProfileFieldsMixin):
    pass


class ProfileCredentialsUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    username: str | None = Field(
        default=None,
        min_length=3,
        max_length=30,
        pattern=r"^[a-zA-Z0-9_.-]+$",
    )
    email: str | None = Field(default=None, min_length=5, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=72)
    nonce: str | None = Field(default=None, min_length=4, max_length=20)
    email_redirect_to: str | None = Field(default=None, max_length=500)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip().lower()

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip().lower()

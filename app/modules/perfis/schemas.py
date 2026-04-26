from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PerfilResponse(BaseModel):
    id: str
    nome: str
    email: str | None = None
    bio: str | None = None
    cidade: str | None = None
    foto_url: str | None = None
    criado_em: datetime | None = None
    atualizado_em: datetime | None = None


class PerfilCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    nome: str = Field(..., min_length=1, max_length=120)
    email: str | None = Field(default=None, max_length=255)
    bio: str | None = Field(default=None, max_length=500)
    cidade: str | None = Field(default=None, max_length=80)

    @field_validator("nome", "bio", "cidade", "email", mode="before")
    @classmethod
    def vazio_para_none(cls, v: str | None) -> str | None:
        if isinstance(v, str):
            return v.strip() or None
        return v


class PerfilUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    nome: str | None = Field(default=None, min_length=1, max_length=120)
    email: str | None = Field(default=None, max_length=255)
    bio: str | None = Field(default=None, max_length=500)
    cidade: str | None = Field(default=None, max_length=80)

    @field_validator("nome", "bio", "cidade", "email", mode="before")
    @classmethod
    def vazio_para_none(cls, v: str | None) -> str | None:
        if isinstance(v, str):
            return v.strip() or None
        return v


class PerfilListResponse(BaseModel):
    items: list[PerfilResponse]
    total: int

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MembroSchema(BaseModel):
    nome: str = Field(..., min_length=1, max_length=80)
    email: str | None = Field(default=None, max_length=255)


class GrupoResponse(BaseModel):
    id: str
    nome: str
    tipo: str
    descricao: str | None = None
    membros: list[MembroSchema] = Field(default_factory=list)
    criado_em: datetime | None = None
    atualizado_em: datetime | None = None


class GrupoCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    nome: str = Field(..., min_length=1, max_length=80)
    tipo: str = Field(default="casal", pattern="^(casal|grupo)$")
    descricao: str | None = Field(default=None, max_length=500)
    membros: list[MembroSchema] = Field(default_factory=list)

    @field_validator("nome", "descricao", mode="before")
    @classmethod
    def vazio_para_none(cls, v: str | None) -> str | None:
        if isinstance(v, str):
            return v.strip() or None
        return v


class GrupoUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    nome: str | None = Field(default=None, min_length=1, max_length=80)
    tipo: str | None = Field(default=None, pattern="^(casal|grupo)$")
    descricao: str | None = Field(default=None, max_length=500)
    membros: list[MembroSchema] | None = None


class GrupoListResponse(BaseModel):
    items: list[GrupoResponse]
    total: int

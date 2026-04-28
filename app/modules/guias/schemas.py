from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.lugares.schemas import LugarResponse


class GuiaResponse(BaseModel):
    id: str
    grupo_id: str
    nome: str
    descricao: str | None = None
    lugar_ids: list[str] = Field(default_factory=list)
    lugares: list[LugarResponse] = Field(default_factory=list)
    total_lugares: int = 0
    criado_em: datetime | None = None
    atualizado_em: datetime | None = None


class GuiaListResponse(BaseModel):
    items: list[GuiaResponse]
    total: int


class GuiaCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    grupo_id: str = Field(..., min_length=8, max_length=64)
    nome: str = Field(..., min_length=1, max_length=80)
    descricao: str | None = Field(default=None, max_length=500)
    lugar_ids: list[str] = Field(default_factory=list, max_length=200)

    @field_validator("grupo_id", "nome", "descricao", mode="before")
    @classmethod
    def vazio_para_none(cls, value: str | None) -> str | None:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("lugar_ids", mode="before")
    @classmethod
    def normalizar_lista_lugares(cls, value: list[str] | None) -> list[str]:
        return _normalizar_lugar_ids(value)


class GuiaUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    nome: str | None = Field(default=None, min_length=1, max_length=80)
    descricao: str | None = Field(default=None, max_length=500)
    lugar_ids: list[str] | None = Field(default=None, max_length=200)

    @field_validator("nome", "descricao", mode="before")
    @classmethod
    def vazio_para_none(cls, value: str | None) -> str | None:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("lugar_ids", mode="before")
    @classmethod
    def normalizar_lista_lugares(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return _normalizar_lugar_ids(value)


class GuiaLugarRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    lugar_id: str = Field(..., min_length=8, max_length=64)

    @field_validator("lugar_id", mode="before")
    @classmethod
    def vazio_para_none(cls, value: str | None) -> str | None:
        if isinstance(value, str):
            return value.strip() or None
        return value


class GuiaReordenarLugaresRequest(BaseModel):
    lugar_ids: list[str] = Field(..., min_length=1, max_length=200)

    @field_validator("lugar_ids", mode="before")
    @classmethod
    def normalizar_lista_lugares(cls, value: list[str] | None) -> list[str]:
        return _normalizar_lugar_ids(value)


def _normalizar_lugar_ids(value: list[str] | None) -> list[str]:
    if not value:
        return []

    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result

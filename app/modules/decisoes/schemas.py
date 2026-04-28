from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.lugares.schemas import LugarResponse


class EscopoDecisao(str, Enum):
    TODOS = "todos"
    FAVORITOS = "favoritos"
    QUERO_IR = "quero_ir"
    GUIA = "guia"


class CriteriosDecisao(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    dia_semana: str | None = Field(default=None, max_length=40)
    clima: str | None = Field(default=None, max_length=80)
    mood: str | None = Field(default=None, max_length=160)
    ocasiao: str | None = Field(default=None, max_length=120)
    orcamento_max: int | None = Field(default=None, ge=1, le=4)
    orcamento_texto: str | None = Field(default=None, max_length=120)
    quantidade_pessoas: int | None = Field(default=None, ge=1, le=30)
    preferencias: list[str] = Field(default_factory=list, max_length=20)
    restricoes: list[str] = Field(default_factory=list, max_length=20)
    observacoes: str | None = Field(default=None, max_length=800)
    priorizar_novidade: bool = False
    surpreender: bool = False

    @field_validator(
        "dia_semana",
        "clima",
        "mood",
        "ocasiao",
        "orcamento_texto",
        "observacoes",
        mode="before",
    )
    @classmethod
    def vazio_para_none(cls, value: str | None) -> str | None:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("preferencias", "restricoes", mode="before")
    @classmethod
    def normalizar_lista_texto(cls, value: list[str] | None) -> list[str]:
        return _normalizar_lista_texto(value)


class DecidirRestauranteRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    grupo_id: str = Field(..., min_length=8, max_length=64)
    escopo: EscopoDecisao = EscopoDecisao.TODOS
    guia_id: str | None = Field(default=None, min_length=8, max_length=64)
    criterios: CriteriosDecisao = Field(default_factory=CriteriosDecisao)
    evitar_lugar_ids: list[str] = Field(default_factory=list, max_length=100)
    max_candidatos: int = Field(default=80, ge=1, le=100)

    @field_validator("grupo_id", "guia_id", mode="before")
    @classmethod
    def vazio_para_none(cls, value: str | None) -> str | None:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("evitar_lugar_ids", mode="before")
    @classmethod
    def normalizar_lugar_ids(cls, value: list[str] | None) -> list[str]:
        return _normalizar_lista_texto(value)


class DecisaoRestauranteItem(BaseModel):
    lugar: LugarResponse
    motivo: str
    pontos_fortes: list[str] = Field(default_factory=list)
    ressalvas: list[str] = Field(default_factory=list)
    confianca: float = Field(default=0.7, ge=0, le=1)


class DecidirRestauranteResponse(BaseModel):
    grupo_id: str
    escopo: EscopoDecisao
    guia_id: str | None = None
    escolha: DecisaoRestauranteItem
    alternativas: list[DecisaoRestauranteItem] = Field(default_factory=list)
    total_candidatos: int
    criterios_usados: dict[str, Any] = Field(default_factory=dict)
    modelo: str
    provider: str = "openai"


def _normalizar_lista_texto(value: list[str] | None) -> list[str]:
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

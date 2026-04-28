from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StatusLugar(str, Enum):
    QUERO_IR = "quero_ir"
    FOMOS = "fomos"
    QUERO_VOLTAR = "quero_voltar"
    NAO_CURTI = "nao_curti"


class OrdenarPor(str, Enum):
    CRIADO_EM = "criado_em"
    ATUALIZADO_EM = "atualizado_em"
    NOME = "nome"


class OrdemDirecao(str, Enum):
    ASC = "asc"
    DESC = "desc"


class FotoSchema(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    url: str
    caminho: str
    ordem: int = 0
    capa: bool = False


class LugarResponse(BaseModel):
    id: str
    grupo_id: str
    nome: str
    categoria: str | None = None
    bairro: str | None = None
    cidade: str | None = None
    faixa_preco: int | None = Field(default=None, ge=1, le=4)
    link: str | None = None
    notas: str | None = None
    status: StatusLugar = StatusLugar.QUERO_IR
    favorito: bool = False
    imagem_capa: str | None = None
    fotos: list[FotoSchema] = Field(default_factory=list)
    adicionado_por: str | None = None
    adicionado_por_perfil_id: str | None = None
    extra: dict = Field(default_factory=dict)
    criado_em: datetime | None = None
    atualizado_em: datetime | None = None


class LugarListResponse(BaseModel):
    items: list[LugarResponse]
    pagina: int
    tamanho_pagina: int
    total: int
    tem_mais: bool


class LugarCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    grupo_id: str = Field(..., min_length=8, max_length=64)
    nome: str = Field(..., min_length=1, max_length=120)
    categoria: str | None = Field(default=None, max_length=80)
    bairro: str | None = Field(default=None, max_length=80)
    cidade: str | None = Field(default=None, max_length=80)
    faixa_preco: int | None = Field(default=None, ge=1, le=4)
    link: str | None = Field(default=None, max_length=500)
    notas: str | None = Field(default=None, max_length=2000)
    status: StatusLugar = StatusLugar.QUERO_IR
    favorito: bool = False
    adicionado_por: str | None = Field(default=None, max_length=80)
    adicionado_por_perfil_id: str | None = Field(default=None, min_length=8, max_length=64)

    @field_validator("link", mode="before")
    @classmethod
    def validar_url(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("Link deve começar com http:// ou https://")
        return v

    @field_validator(
        "nome",
        "categoria",
        "bairro",
        "cidade",
        "notas",
        "adicionado_por",
        "adicionado_por_perfil_id",
        mode="before",
    )
    @classmethod
    def vazio_para_none(cls, v: str | None) -> str | None:
        if isinstance(v, str):
            return v.strip() or None
        return v


class LugarUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    nome: str | None = Field(default=None, min_length=1, max_length=120)
    categoria: str | None = Field(default=None, max_length=80)
    bairro: str | None = Field(default=None, max_length=80)
    cidade: str | None = Field(default=None, max_length=80)
    faixa_preco: int | None = Field(default=None, ge=1, le=4)
    link: str | None = Field(default=None, max_length=500)
    notas: str | None = Field(default=None, max_length=2000)
    status: StatusLugar | None = None
    favorito: bool | None = None
    adicionado_por: str | None = Field(default=None, max_length=80)
    adicionado_por_perfil_id: str | None = Field(default=None, min_length=8, max_length=64)

    @field_validator("link", mode="before")
    @classmethod
    def validar_url(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("Link deve começar com http:// ou https://")
        return v


    @field_validator("adicionado_por", "adicionado_por_perfil_id", mode="before")
    @classmethod
    def vazio_para_none(cls, v: str | None) -> str | None:
        if isinstance(v, str):
            return v.strip() or None
        return v


class LugarFiltros(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    grupo_id: str
    pagina: int = Field(default=1, ge=1)
    tamanho_pagina: int = Field(default=20, ge=1, le=100)
    busca: str | None = Field(default=None, max_length=120)
    categoria: str | None = Field(default=None, max_length=80)
    bairro: str | None = Field(default=None, max_length=80)
    status: StatusLugar | None = None
    favorito: bool | None = None
    faixa_preco: int | None = Field(default=None, ge=1, le=4)
    faixa_preco_min: int | None = Field(default=None, ge=1, le=4)
    faixa_preco_max: int | None = Field(default=None, ge=1, le=4)
    ordenar_por: OrdenarPor = OrdenarPor.CRIADO_EM
    direcao: OrdemDirecao = OrdemDirecao.DESC

    def para_filtros_supabase(self) -> list[tuple[str, str]]:
        filtros: list[tuple[str, str]] = []
        if self.busca:
            termo = self.busca.strip().replace("*", " ").replace("(", " ").replace(")", " ")
            if termo:
                filtros.append(("or", f"(nome.ilike.*{termo}*,categoria.ilike.*{termo}*,bairro.ilike.*{termo}*)"))
        if self.categoria:
            filtros.append(("categoria", f"ilike.*{self.categoria}*"))
        if self.bairro:
            filtros.append(("bairro", f"ilike.*{self.bairro}*"))
        if self.status:
            filtros.append(("status", f"eq.{self.status.value}"))
        if self.favorito is not None:
            filtros.append(("favorito", f"eq.{str(self.favorito).lower()}"))
        if self.faixa_preco is not None:
            filtros.append(("faixa_preco", f"eq.{self.faixa_preco}"))
        if self.faixa_preco_min is not None:
            filtros.append(("faixa_preco", f"gte.{self.faixa_preco_min}"))
        if self.faixa_preco_max is not None:
            filtros.append(("faixa_preco", f"lte.{self.faixa_preco_max}"))
        return filtros


class ReordenarFotosRequest(BaseModel):
    ids_fotos: list[str] = Field(..., min_length=1, max_length=30)

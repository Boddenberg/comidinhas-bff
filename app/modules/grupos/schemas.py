from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TipoGrupo(str, Enum):
    INDIVIDUAL = "individual"
    CASAL = "casal"
    GRUPO = "grupo"


class PapelMembro(str, Enum):
    DONO = "dono"
    ADMINISTRADOR = "administrador"
    MEMBRO = "membro"


class StatusSolicitacaoGrupo(str, Enum):
    PENDENTE = "pendente"
    ACEITA = "aceita"
    RECUSADA = "recusada"


class MembroSchema(BaseModel):
    perfil_id: str | None = Field(default=None, min_length=8, max_length=64)
    nome: str | None = Field(default=None, min_length=1, max_length=120)
    email: str | None = Field(default=None, max_length=255)
    papel: PapelMembro = PapelMembro.MEMBRO

    @field_validator("nome", "email", "perfil_id", mode="before")
    @classmethod
    def vazio_para_none(cls, v: str | None) -> str | None:
        if isinstance(v, str):
            return v.strip() or None
        return v

    @field_validator("email")
    @classmethod
    def normalizar_email(cls, v: str | None) -> str | None:
        return v.lower() if isinstance(v, str) else v


class SolicitacaoEntradaGrupoSchema(BaseModel):
    id: str
    perfil_id: str = Field(..., min_length=8, max_length=64)
    nome: str | None = Field(default=None, min_length=1, max_length=120)
    email: str | None = Field(default=None, max_length=255)
    mensagem: str | None = Field(default=None, max_length=500)
    status: StatusSolicitacaoGrupo = StatusSolicitacaoGrupo.PENDENTE
    solicitado_em: datetime | None = None
    respondido_em: datetime | None = None
    respondido_por_perfil_id: str | None = Field(default=None, min_length=8, max_length=64)


class GrupoResponse(BaseModel):
    id: str
    codigo: str | None = None
    nome: str
    tipo: TipoGrupo
    descricao: str | None = None
    foto_url: str | None = None
    dono_perfil_id: str | None = None
    membros: list[MembroSchema] = Field(default_factory=list)
    solicitacoes: list[SolicitacaoEntradaGrupoSchema] = Field(default_factory=list)
    criado_em: datetime | None = None
    atualizado_em: datetime | None = None


class GrupoCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    nome: str = Field(..., min_length=1, max_length=80)
    tipo: TipoGrupo = TipoGrupo.CASAL
    descricao: str | None = Field(default=None, max_length=500)
    foto_url: str | None = Field(default=None, max_length=1000)
    dono_perfil_id: str | None = Field(default=None, min_length=8, max_length=64)
    membros: list[MembroSchema] = Field(default_factory=list)

    @field_validator("nome", "descricao", "foto_url", "dono_perfil_id", mode="before")
    @classmethod
    def vazio_para_none(cls, v: str | None) -> str | None:
        if isinstance(v, str):
            return v.strip() or None
        return v

    @model_validator(mode="after")
    def validar_integrantes(self) -> "GrupoCreateRequest":
        if self.tipo == TipoGrupo.INDIVIDUAL and not self.dono_perfil_id and not self.membros:
            raise ValueError("Para criar um espaco individual, informe dono_perfil_id ou membros.")
        if self.tipo == TipoGrupo.CASAL and len(self.membros) < 2 and not self.dono_perfil_id:
            raise ValueError("Para criar um casal, informe dois membros cadastrados.")
        if self.tipo == TipoGrupo.GRUPO and not self.dono_perfil_id:
            raise ValueError("Para criar um grupo, informe o dono_perfil_id.")
        return self


class GrupoUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    nome: str | None = Field(default=None, min_length=1, max_length=80)
    tipo: TipoGrupo | None = None
    descricao: str | None = Field(default=None, max_length=500)
    foto_url: str | None = Field(default=None, max_length=1000)
    dono_perfil_id: str | None = Field(default=None, min_length=8, max_length=64)
    membros: list[MembroSchema] | None = None
    responsavel_perfil_id: str | None = Field(default=None, min_length=8, max_length=64)


class GrupoListResponse(BaseModel):
    items: list[GrupoResponse]
    total: int


class GrupoMembroRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    perfil_id: str | None = Field(default=None, min_length=8, max_length=64)
    email: str | None = Field(default=None, min_length=3, max_length=255)
    papel: PapelMembro = PapelMembro.MEMBRO
    responsavel_perfil_id: str | None = Field(default=None, min_length=8, max_length=64)

    @field_validator("email", "perfil_id", "responsavel_perfil_id", mode="before")
    @classmethod
    def vazio_para_none(cls, v: str | None) -> str | None:
        if isinstance(v, str):
            return v.strip() or None
        return v

    @field_validator("email")
    @classmethod
    def normalizar_email(cls, v: str | None) -> str | None:
        return v.lower() if isinstance(v, str) else v

    @model_validator(mode="after")
    def validar_identificador(self) -> "GrupoMembroRequest":
        if not self.perfil_id and not self.email:
            raise ValueError("Informe perfil_id ou email do membro.")
        return self


class SolicitacaoEntradaGrupoRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    perfil_id: str = Field(..., min_length=8, max_length=64)
    mensagem: str | None = Field(default=None, max_length=500)


class SolicitacaoEntradaGrupoListResponse(BaseModel):
    items: list[SolicitacaoEntradaGrupoSchema]
    total: int


class ResponderSolicitacaoGrupoRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    responsavel_perfil_id: str = Field(..., min_length=8, max_length=64)


class PapelMembroUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    responsavel_perfil_id: str = Field(..., min_length=8, max_length=64)
    papel: PapelMembro

    @model_validator(mode="after")
    def validar_papel(self) -> "PapelMembroUpdateRequest":
        if self.papel == PapelMembro.DONO:
            raise ValueError("Use este endpoint apenas para administrador ou membro.")
        return self

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class LugarResumo(BaseModel):
    id: str
    nome: str
    categoria: str | None = None
    bairro: str | None = None
    cidade: str | None = None
    faixa_preco: int | None = None
    status: str | None = None
    favorito: bool = False
    imagem_capa: str | None = None
    adicionado_por: str | None = None
    criado_em: datetime | None = None


class GrupoResumo(BaseModel):
    id: str
    nome: str
    tipo: str
    descricao: str | None = None
    membros: list[Any] = Field(default_factory=list)
    criado_em: datetime | None = None
    atualizado_em: datetime | None = None


class Contadores(BaseModel):
    total: int = 0
    visitados: int = 0
    favoritos: int = 0
    quero_ir: int = 0
    quero_voltar: int = 0


class HomeResponse(BaseModel):
    grupo: GrupoResumo | None = None
    contadores: Contadores = Field(default_factory=Contadores)
    favoritos: list[LugarResumo] = Field(default_factory=list)
    recentes: list[LugarResumo] = Field(default_factory=list)
    quero_ir: list[LugarResumo] = Field(default_factory=list)
    quero_voltar: list[LugarResumo] = Field(default_factory=list)

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.lugares.schemas import StatusLugar


class RestauranteBase(BaseModel):
    id: str
    nome: str
    categoria_id: str
    categoria: str
    tipo: str | None = None
    endereco: str | None = None
    bairro: str | None = None
    cidade: str = "São Paulo"
    distincao: str | None = None
    descricao: str | None = None
    fonte_chunk: str | None = None
    markdown: str | None = None
    termos_busca: list[str] = Field(default_factory=list)


class CategoriaBase(BaseModel):
    id: str
    numero: int
    titulo: str
    total_restaurantes: int
    chunk: str


class RestaurantesBaseStats(BaseModel):
    versao: str
    cidade: str
    fonte: str
    total_restaurantes: int
    total_categorias: int
    categorias: list[CategoriaBase] = Field(default_factory=list)


class BuscarRestaurantesBaseRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(..., min_length=1, max_length=300)
    categoria: str | None = Field(default=None, max_length=120)
    bairro: str | None = Field(default=None, max_length=80)
    max_resultados: int = Field(default=10, ge=1, le=50)
    incluir_markdown: bool = False

    @field_validator("query", "categoria", "bairro", mode="before")
    @classmethod
    def vazio_para_none(cls, value: str | None) -> str | None:
        if isinstance(value, str):
            return value.strip() or None
        return value


class RestauranteBaseResultado(BaseModel):
    restaurante: RestauranteBase
    score: float
    trechos: list[str] = Field(default_factory=list)


class BuscarRestaurantesBaseResponse(BaseModel):
    query: str
    total: int
    items: list[RestauranteBaseResultado]
    versao: str
    cidade: str


class SalvarRestauranteBaseRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    restaurante_id: str = Field(..., min_length=1, max_length=160)
    grupo_id: str = Field(..., min_length=8, max_length=64)
    status: StatusLugar = StatusLugar.QUERO_IR
    favorito: bool = False
    notas: str | None = Field(default=None, max_length=2000)
    adicionado_por: str | None = Field(default=None, max_length=80)
    adicionado_por_perfil_id: str | None = Field(default=None, min_length=8, max_length=64)

    @field_validator(
        "restaurante_id",
        "grupo_id",
        "notas",
        "adicionado_por",
        "adicionado_por_perfil_id",
        mode="before",
    )
    @classmethod
    def vazio_para_none(cls, value: str | None) -> str | None:
        if isinstance(value, str):
            return value.strip() or None
        return value

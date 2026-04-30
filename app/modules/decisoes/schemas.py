from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.lugares.schemas import LugarResponse, StatusLugar


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


class IntencaoPedido(str, Enum):
    RECOMENDACAO_RESTAURANTE = "recomendacao_restaurante"
    FORA_ESCOPO = "fora_escopo"


class EstrategiaRecomendacao(str, Enum):
    INTERNA = "interna"
    GOOGLE = "google"
    HIBRIDA = "hibrida"


class PreferenciaNovidade(str, Enum):
    AUTO = "auto"
    NOVO = "novo"
    SEGURO = "seguro"


class EstadoRecomendacao(str, Enum):
    OPCOES = "opcoes"
    PRECISA_REFINAR = "precisa_refinar"
    FORA_ESCOPO = "fora_escopo"


class OrigemCandidato(str, Enum):
    COMIDINHAS = "comidinhas"
    GOOGLE = "google"


class LocalizacaoRecomendacao(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    cidade: str | None = Field(default=None, max_length=80)
    bairro: str | None = Field(default=None, max_length=80)
    raio_metros: int = Field(default=8000, ge=100, le=50000)

    @field_validator("cidade", "bairro", mode="before")
    @classmethod
    def vazio_para_none(cls, value: str | None) -> str | None:
        if isinstance(value, str):
            return value.strip() or None
        return value


class InterpretacaoRecomendacao(BaseModel):
    intencao: IntencaoPedido = IntencaoPedido.RECOMENDACAO_RESTAURANTE
    cozinhas: list[str] = Field(default_factory=list)
    termos_busca: list[str] = Field(default_factory=list)
    momento: str | None = None
    localizacao_texto: str | None = None
    estrategia: EstrategiaRecomendacao = EstrategiaRecomendacao.HIBRIDA
    precisa_localizacao: bool = False
    preferencia_novidade: PreferenciaNovidade = PreferenciaNovidade.AUTO
    preferencias: list[str] = Field(default_factory=list)
    restricoes: list[str] = Field(default_factory=list)
    orcamento_max: int | None = Field(default=None, ge=1, le=4)
    quantidade_pessoas: int | None = Field(default=None, ge=1, le=30)
    pergunta_refinamento: str | None = None
    confianca: float = Field(default=0.7, ge=0, le=1)

    @field_validator("cozinhas", "termos_busca", "preferencias", "restricoes", mode="before")
    @classmethod
    def normalizar_lista_texto(cls, value: list[str] | None) -> list[str]:
        return _normalizar_lista_texto(value)

    @field_validator("momento", "localizacao_texto", "pergunta_refinamento", mode="before")
    @classmethod
    def vazio_para_none(cls, value: str | None) -> str | None:
        if isinstance(value, str):
            return value.strip() or None
        return value


class RecomendarRestaurantesRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    grupo_id: str = Field(..., min_length=8, max_length=64)
    mensagem: str = Field(..., min_length=1, max_length=1000)
    perfil_id: str | None = Field(default=None, min_length=8, max_length=64)
    localizacao: LocalizacaoRecomendacao | None = None
    permitir_google: bool = True
    max_resultados: int = Field(default=6, ge=1, le=10)
    max_candidatos_internos: int = Field(default=80, ge=1, le=100)
    max_candidatos_google: int = Field(default=10, ge=1, le=20)

    @field_validator("grupo_id", "perfil_id", mode="before")
    @classmethod
    def vazio_para_none(cls, value: str | None) -> str | None:
        if isinstance(value, str):
            return value.strip() or None
        return value


class CandidatoRestaurante(BaseModel):
    candidato_id: str
    origem: OrigemCandidato
    lugar_id: str | None = None
    google_place_id: str | None = None
    nome: str
    categoria: str | None = None
    bairro: str | None = None
    cidade: str | None = None
    endereco: str | None = None
    faixa_preco: int | None = Field(default=None, ge=1, le=4)
    rating: float | None = None
    user_rating_count: int | None = None
    status: StatusLugar | None = None
    favorito: bool = False
    ja_fomos: bool = False
    novo_no_app: bool = False
    aberto_agora: bool | None = None
    imagem_capa: str | None = None
    fotos: list[dict[str, Any]] = Field(default_factory=list)
    link: str | None = None
    google_maps_uri: str | None = None
    website_uri: str | None = None
    telefone: str | None = None


class RecomendacaoRestauranteItem(BaseModel):
    restaurante: CandidatoRestaurante
    motivo: str
    pontos_fortes: list[str] = Field(default_factory=list)
    ressalvas: list[str] = Field(default_factory=list)
    confianca: float = Field(default=0.7, ge=0, le=1)


class RecomendarRestaurantesResponse(BaseModel):
    grupo_id: str
    estado: EstadoRecomendacao
    mensagem: str
    interpretacao: InterpretacaoRecomendacao
    resumo: str | None = None
    pergunta_refinamento: str | None = None
    opcoes: list[RecomendacaoRestauranteItem] = Field(default_factory=list)
    total_candidatos: int = 0
    fontes_usadas: list[OrigemCandidato] = Field(default_factory=list)
    modelo: str
    provider: str = "openai"


class TodayRecommendationsRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    grupo_id: str = Field(..., min_length=8, max_length=64)
    perfil_id: str | None = Field(default=None, min_length=8, max_length=64)
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    limit: int = Field(default=3, ge=1, le=3)
    radius_meters: int = Field(default=2500, ge=100, le=50000)
    mood: str | None = Field(default=None, max_length=160)
    weather: str | None = Field(default=None, max_length=160)

    @field_validator("grupo_id", "perfil_id", "mood", "weather", mode="before")
    @classmethod
    def vazio_para_none(cls, value: str | None) -> str | None:
        if isinstance(value, str):
            return value.strip() or None
        return value


class TodayRecommendationItem(BaseModel):
    id: str
    google_place_id: str
    group_id: str
    name: str
    category: str | None = None
    neighborhood: str | None = None
    city: str | None = None
    price_range: int | None = Field(default=None, ge=1, le=4)
    link: str | None = None
    notes: str | None = None
    status: StatusLugar = StatusLugar.QUERO_IR
    is_favorite: bool = False
    image_url: str | None = None
    rating: float | None = None
    user_rating_count: int | None = None
    added_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    photos: list[dict[str, Any]] = Field(default_factory=list)
    formatted_address: str | None = None
    recommendation_reason: str | None = None


class TodayRecommendationsResponse(BaseModel):
    generated_at: str
    places: list[TodayRecommendationItem] = Field(default_factory=list)
    total_candidates: int = 0
    model: str
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

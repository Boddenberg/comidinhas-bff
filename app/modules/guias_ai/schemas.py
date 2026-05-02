from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class JobStatus(str, Enum):
    CREATED = "created"
    SANITIZING_TEXT = "sanitizing_text"
    CLASSIFYING_CONTENT = "classifying_content"
    EXTRACTING_GUIDE_METADATA = "extracting_guide_metadata"
    EXTRACTING_RESTAURANTS = "extracting_restaurants"
    MATCHING_INTERNAL_RESTAURANTS = "matching_internal_restaurants"
    SEARCHING_GOOGLE_PLACES = "searching_google_places"
    ENRICHING_PLACES = "enriching_places"
    SELECTING_PHOTOS = "selecting_photos"
    CALCULATING_GROUP_SUGGESTIONS = "calculating_group_suggestions"
    CREATING_GUIDE = "creating_guide"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    INVALID_CONTENT = "invalid_content"
    FAILED = "failed"


JOB_PROGRESS: dict[JobStatus, int] = {
    JobStatus.CREATED: 1,
    JobStatus.SANITIZING_TEXT: 5,
    JobStatus.CLASSIFYING_CONTENT: 12,
    JobStatus.EXTRACTING_GUIDE_METADATA: 22,
    JobStatus.EXTRACTING_RESTAURANTS: 35,
    JobStatus.MATCHING_INTERNAL_RESTAURANTS: 48,
    JobStatus.SEARCHING_GOOGLE_PLACES: 62,
    JobStatus.ENRICHING_PLACES: 76,
    JobStatus.SELECTING_PHOTOS: 84,
    JobStatus.CALCULATING_GROUP_SUGGESTIONS: 90,
    JobStatus.CREATING_GUIDE: 96,
    JobStatus.COMPLETED: 100,
    JobStatus.COMPLETED_WITH_WARNINGS: 100,
    JobStatus.INVALID_CONTENT: 100,
    JobStatus.FAILED: 100,
}


JOB_USER_LABEL: dict[JobStatus, str] = {
    JobStatus.CREATED: "Recebido",
    JobStatus.SANITIZING_TEXT: "Lendo o texto",
    JobStatus.CLASSIFYING_CONTENT: "Avaliando o conteudo",
    JobStatus.EXTRACTING_GUIDE_METADATA: "Identificando o guia",
    JobStatus.EXTRACTING_RESTAURANTS: "Identificando restaurantes",
    JobStatus.MATCHING_INTERNAL_RESTAURANTS: "Cruzando com seus restaurantes",
    JobStatus.SEARCHING_GOOGLE_PLACES: "Buscando dados no Maps",
    JobStatus.ENRICHING_PLACES: "Enriquecendo dados",
    JobStatus.SELECTING_PHOTOS: "Escolhendo fotos",
    JobStatus.CALCULATING_GROUP_SUGGESTIONS: "Calculando sugestoes",
    JobStatus.CREATING_GUIDE: "Montando o guia",
    JobStatus.COMPLETED: "Guia criado",
    JobStatus.COMPLETED_WITH_WARNINGS: "Guia criado com pendencias",
    JobStatus.INVALID_CONTENT: "Conteudo invalido",
    JobStatus.FAILED: "Falhou",
}


class TipoConteudo(str, Enum):
    RANKING_GASTRONOMICO = "ranking_gastronomico"
    GUIA_GASTRONOMICO = "guia_gastronomico"
    LISTA_EDITORIAL = "lista_editorial"
    REVIEW_INDIVIDUAL = "review_individual"
    RECEITA = "receita"
    NAO_GASTRONOMICO = "nao_gastronomico"
    INSUFICIENTE = "insuficiente"


class StatusMatching(str, Enum):
    ENCONTRADO_INTERNO = "encontrado_interno"
    ENCONTRADO_GOOGLE = "encontrado_google"
    CRIADO_AUTOMATICAMENTE = "criado_automaticamente"
    POSSIVEL_DUPLICADO = "possivel_duplicado"
    PENDENTE = "pendente"
    NAO_ENCONTRADO = "nao_encontrado"
    BAIXA_CONFIANCA = "baixa_confianca"
    POSSIVELMENTE_FECHADO = "possivelmente_fechado"
    DADOS_INCOMPLETOS = "dados_incompletos"
    IGNORADO = "ignorado"
    CONFIRMADO_USUARIO = "confirmado_usuario"


class CriarGuiaIaRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    grupo_id: str = Field(..., min_length=8, max_length=64)
    perfil_id: str | None = Field(default=None, min_length=8, max_length=64)
    texto: str = Field(..., min_length=10, max_length=400_000)
    titulo_sugerido: str | None = Field(default=None, max_length=200)
    url_origem: str | None = Field(default=None, max_length=1000)

    @field_validator("perfil_id", "titulo_sugerido", "url_origem", mode="before")
    @classmethod
    def vazio_para_none(cls, value: str | None) -> str | None:
        if isinstance(value, str):
            return value.strip() or None
        return value


class JobEtapaProgresso(BaseModel):
    etapa: str
    iniciado_em: datetime | None = None
    concluido_em: datetime | None = None
    sucesso: bool = True
    detalhe: str | None = None


class JobResumoEstatisticas(BaseModel):
    restaurantes_extraidos: int = 0
    restaurantes_salvos: int = 0
    matches_internos: int = 0
    buscas_google: int = 0
    enriquecidos_google: int = 0
    fotos_encontradas: int = 0
    pendencias: int = 0
    chamadas_llm: int = 0
    chamadas_google: int = 0
    custo_estimado_brl: float | None = None
    duracao_ms: int | None = None


class JobResponse(BaseModel):
    id: str
    grupo_id: str
    perfil_id: str | None = None
    guia_id: str | None = None
    status: JobStatus
    etapa_atual: str | None = None
    etapas_concluidas: list[str] = Field(default_factory=list)
    progresso_percentual: int = 0
    progresso_label: str | None = None
    mensagem_usuario: str | None = None
    motivo_invalido: str | None = None
    alertas: list[str] = Field(default_factory=list)
    estatisticas: JobResumoEstatisticas = Field(default_factory=JobResumoEstatisticas)
    iniciado_em: datetime | None = None
    concluido_em: datetime | None = None
    criado_em: datetime | None = None
    atualizado_em: datetime | None = None


class GuiaIaItemResponse(BaseModel):
    id: str
    posicao_ranking: int | None = None
    ordem: int = 0
    nome_importado: str
    nome_normalizado: str | None = None
    bairro: str | None = None
    cidade: str | None = None
    estado: str | None = None
    categoria: str | None = None
    place_id: str | None = None
    endereco: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    google_maps_uri: str | None = None
    telefone: str | None = None
    site: str | None = None
    rating: float | None = None
    total_avaliacoes: int | None = None
    preco_nivel: int | None = None
    foto_url: str | None = None
    foto_atribuicao: str | None = None
    status_negocio: str | None = None
    horarios: list[str] = Field(default_factory=list)
    status_matching: StatusMatching = StatusMatching.PENDENTE
    score_matching: float | None = None
    confianca_extracao: float | None = None
    confianca_enriquecimento: float | None = None
    alertas: list[str] = Field(default_factory=list)
    trecho_original: str | None = None
    lugar_id: str | None = None
    lugar_status: str | None = None
    lugar_favorito: bool | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class GuiaIaSugestaoCard(BaseModel):
    id: str
    titulo: str
    motivo: str
    item_id: str | None = None
    nome: str | None = None
    foto_url: str | None = None
    bairro: str | None = None
    cidade: str | None = None
    google_maps_uri: str | None = None
    score: float | None = None


class GuiaIaSugestoes(BaseModel):
    melhor_para_hoje: GuiaIaSugestaoCard | None = None
    mais_facil_para_todos: GuiaIaSugestaoCard | None = None
    melhor_avaliado: GuiaIaSugestaoCard | None = None
    mais_desejado_pelo_grupo: GuiaIaSugestaoCard | None = None
    novidade_para_o_grupo: GuiaIaSugestaoCard | None = None
    aviso_privacidade: str | None = None


class GuiaIaResponse(BaseModel):
    id: str
    grupo_id: str
    nome: str
    descricao: str | None = None
    tipo_guia: str = "ia"
    fonte: str | None = None
    autor: str | None = None
    url_origem: str | None = None
    data_publicacao: datetime | None = None
    categoria: str | None = None
    regiao: str | None = None
    cidade_principal: str | None = None
    imagem_capa: str | None = None
    total_itens: int = 0
    status_importacao: str | None = None
    qualidade_importacao: str | None = None
    alertas: list[str] = Field(default_factory=list)
    metadados: dict[str, Any] = Field(default_factory=dict)
    sugestoes: GuiaIaSugestoes = Field(default_factory=GuiaIaSugestoes)
    itens: list[GuiaIaItemResponse] = Field(default_factory=list)
    criado_em: datetime | None = None
    atualizado_em: datetime | None = None


class GuiaIaItemUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    nome_importado: str | None = Field(default=None, min_length=1, max_length=200)
    bairro: str | None = Field(default=None, max_length=80)
    cidade: str | None = Field(default=None, max_length=80)
    categoria: str | None = Field(default=None, max_length=80)
    foto_url: str | None = Field(default=None, max_length=1000)
    lugar_id: str | None = Field(default=None, min_length=8, max_length=64)
    desassociar_lugar: bool = False
    status_matching: StatusMatching | None = None
    confirmar: bool = False


class GuiaIaItensReorderRequest(BaseModel):
    item_ids: list[str] = Field(..., min_length=1, max_length=200)


class GuiaIaCapaUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    imagem_capa: str | None = Field(default=None, max_length=1000)
    item_id: str | None = Field(default=None, min_length=8, max_length=64)


class GuiaIaMetadataUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    nome: str | None = Field(default=None, min_length=1, max_length=80)
    descricao: str | None = Field(default=None, max_length=500)
    categoria: str | None = Field(default=None, max_length=80)
    regiao: str | None = Field(default=None, max_length=80)
    cidade_principal: str | None = Field(default=None, max_length=80)


# -------------------------- internal pipeline DTOs (not exposed)
class ExtractedRestaurant(BaseModel):
    posicao_ranking: int | None = None
    ordem: int
    nome_original: str
    nome_normalizado: str
    bairro: str | None = None
    cidade: str | None = None
    estado: str | None = None
    categoria: str | None = None
    unidade: str | None = None
    trecho_original: str | None = None
    confianca_extracao: float = 0.5
    parece_real: bool = True
    parece_ruido: bool = False
    parece_separador: bool = False
    alertas: list[str] = Field(default_factory=list)


class ExtractedGuide(BaseModel):
    titulo: str | None = None
    fonte: str | None = None
    autor: str | None = None
    data_publicacao: str | None = None
    categoria: str | None = None
    cidade_principal: str | None = None
    regiao: str | None = None
    descricao: str | None = None
    tipo_guia_detectado: str | None = None
    quantidade_esperada: int | None = None
    confianca: float = 0.0
    restaurantes: list[ExtractedRestaurant] = Field(default_factory=list)


class ContentClassification(BaseModel):
    tipo: TipoConteudo
    confianca: float
    motivo: str | None = None


class EnrichedItem(BaseModel):
    extracted: ExtractedRestaurant
    place_id: str | None = None
    nome_oficial: str | None = None
    endereco: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    google_maps_uri: str | None = None
    telefone: str | None = None
    site: str | None = None
    rating: float | None = None
    total_avaliacoes: int | None = None
    preco_nivel: int | None = None
    foto_url: str | None = None
    foto_atribuicao: str | None = None
    status_negocio: str | None = None
    horarios: list[str] = Field(default_factory=list)
    aberto_agora: bool | None = None
    bairro_normalizado: str | None = None
    cidade_normalizada: str | None = None
    categorias_google: list[str] = Field(default_factory=list)
    confianca_enriquecimento: float = 0.0
    status_matching: StatusMatching = StatusMatching.PENDENTE
    score_matching: float = 0.0
    lugar_id: str | None = None
    lugar_existente: dict[str, Any] | None = None
    alertas: list[str] = Field(default_factory=list)

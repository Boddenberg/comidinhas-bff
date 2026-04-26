from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PlaceStatus(str, Enum):
    QUERO_IR = "quero_ir"
    FOMOS = "fomos"
    QUERO_VOLTAR = "quero_voltar"
    NAO_CURTI = "nao_curti"


class PlaceSortBy(str, Enum):
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    NAME = "name"


class PlaceSortOrder(str, Enum):
    ASC = "asc"
    DESC = "desc"


class PlaceCreatorResponse(BaseModel):
    id: str
    full_name: str | None = None
    username: str | None = None
    avatar_url: str | None = None


class PlacePhotoResponse(BaseModel):
    id: str
    place_id: str
    group_id: str
    public_url: str
    storage_path: str
    is_cover: bool = False
    sort_order: int = 0
    created_by: str
    created_at: datetime | None = None


class PlaceResponse(BaseModel):
    id: str
    group_id: str
    name: str
    category: str | None = None
    neighborhood: str | None = None
    city: str | None = None
    price_range: int | None = Field(default=None, ge=1, le=4)
    link: str | None = None
    image_url: str | None = None
    notes: str | None = None
    status: PlaceStatus
    is_favorite: bool = False
    created_by: str
    updated_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    creator: PlaceCreatorResponse | None = None
    last_editor: PlaceCreatorResponse | None = None
    photos: list[PlacePhotoResponse] = Field(default_factory=list)


class PlaceListResponse(BaseModel):
    items: list[PlaceResponse]
    page: int
    page_size: int
    total: int
    has_more: bool


class PlaceCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    group_id: str | None = Field(default=None, min_length=8, max_length=64)
    name: str = Field(..., min_length=1, max_length=120)
    category: str | None = Field(default=None, max_length=80)
    neighborhood: str | None = Field(default=None, max_length=80)
    city: str | None = Field(default=None, max_length=80)
    price_range: int | None = Field(default=None, ge=1, le=4)
    link: str | None = Field(default=None, max_length=500)
    image_url: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=1000)
    status: PlaceStatus = PlaceStatus.QUERO_IR
    is_favorite: bool = False

    @field_validator("link", "image_url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if not (normalized.startswith("http://") or normalized.startswith("https://")):
            raise ValueError("URLs devem comecar com http:// ou https://.")
        return normalized

    @field_validator("name", "category", "neighborhood", "city", "notes")
    @classmethod
    def empty_string_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip()
        return normalized or None


class PlaceUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=120)
    category: str | None = Field(default=None, max_length=80)
    neighborhood: str | None = Field(default=None, max_length=80)
    city: str | None = Field(default=None, max_length=80)
    price_range: int | None = Field(default=None, ge=1, le=4)
    link: str | None = Field(default=None, max_length=500)
    image_url: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=1000)
    status: PlaceStatus | None = None
    is_favorite: bool | None = None

    @field_validator("link", "image_url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if not (normalized.startswith("http://") or normalized.startswith("https://")):
            raise ValueError("URLs devem comecar com http:// ou https://.")
        return normalized


class ReorderPhotosRequest(BaseModel):
    photo_ids: list[str] = Field(..., min_length=1, max_length=30)


class PlaceListParams(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    group_id: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    search: str | None = Field(default=None, max_length=120)
    category: str | None = Field(default=None, max_length=80)
    neighborhood: str | None = Field(default=None, max_length=80)
    status: PlaceStatus | None = None
    is_favorite: bool | None = None
    price_range: int | None = Field(default=None, ge=1, le=4)
    price_range_min: int | None = Field(default=None, ge=1, le=4)
    price_range_max: int | None = Field(default=None, ge=1, le=4)
    sort_by: PlaceSortBy = PlaceSortBy.CREATED_AT
    sort_order: PlaceSortOrder = PlaceSortOrder.DESC

    def to_supabase_filters(self) -> list[tuple[str, str]]:
        filters: list[tuple[str, str]] = []
        if self.search:
            term = self._sanitize_token(self.search)
            if term:
                filters.append(
                    (
                        "or",
                        f"(name.ilike.*{term}*,"
                        f"category.ilike.*{term}*,"
                        f"neighborhood.ilike.*{term}*)",
                    ),
                )
        if self.category:
            filters.append(("category", f"ilike.*{self._sanitize_token(self.category)}*"))
        if self.neighborhood:
            filters.append(("neighborhood", f"ilike.*{self._sanitize_token(self.neighborhood)}*"))
        if self.status is not None:
            filters.append(("status", f"eq.{self.status.value}"))
        if self.is_favorite is not None:
            filters.append(("is_favorite", f"eq.{str(self.is_favorite).lower()}"))
        if self.price_range is not None:
            filters.append(("price_range", f"eq.{self.price_range}"))
        if self.price_range_min is not None:
            filters.append(("price_range", f"gte.{self.price_range_min}"))
        if self.price_range_max is not None:
            filters.append(("price_range", f"lte.{self.price_range_max}"))
        return filters

    @staticmethod
    def _sanitize_token(value: str) -> str:
        cleaned = (
            value.replace(",", " ")
            .replace("(", " ")
            .replace(")", " ")
            .replace("*", " ")
            .strip()
        )
        return " ".join(cleaned.split())

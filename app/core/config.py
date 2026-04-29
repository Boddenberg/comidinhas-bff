from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Comidinhas BFF"
    app_env: str = "local"
    app_version: str = "0.1.0"
    web_app_base_url: str = "https://comidinhas-web-production.up.railway.app"
    web_group_invite_path: str = "/entrar"

    cors_allowed_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://localhost:5180",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:5180",
        ]
    )
    cors_allowed_origin_regex: str = (
        r"^https://([a-zA-Z0-9-]+\.)*(comidinhas\.app|up\.railway\.app)$"
    )

    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_chat_model: str = "gpt-4o-mini"
    openai_system_prompt: str = (
        "Voce e o assistente do app Comidinhas. "
        "Responda com clareza, objetividade e foco no contexto de comida."
    )
    openai_timeout_seconds: float = Field(default=30.0, ge=1.0, le=120.0)

    log_level: str = "INFO"
    log_httpx_level: str = "WARNING"
    log_uvicorn_access_level: str = "INFO"
    log_request_body: bool = False
    log_body_max_chars: int = Field(default=2000, ge=100, le=20000)

    google_maps_api_key: str | None = None
    google_places_base_url: str = "https://places.googleapis.com/v1"
    google_places_timeout_seconds: float = Field(default=20.0, ge=1.0, le=120.0)
    google_places_default_language_code: str = "pt-BR"
    google_places_default_region_code: str = "BR"
    google_places_photo_max_width: int = Field(default=600, ge=1, le=4800)
    google_places_photo_max_height: int = Field(default=400, ge=1, le=4800)
    google_places_max_photos_per_place: int = Field(default=10, ge=1, le=10)

    supabase_url: str | None = None
    supabase_key: str | None = None
    supabase_service_role_key: str | None = None
    supabase_timeout_seconds: float = Field(default=20.0, ge=1.0, le=120.0)
    supabase_profile_bucket: str = "profile-photos"
    supabase_profile_photo_max_bytes: int = Field(
        default=2_097_152,
        ge=1,
        le=10_485_760,
    )
    supabase_group_bucket: str = "group-photos"
    supabase_group_photo_max_bytes: int = Field(
        default=2_097_152,
        ge=1,
        le=10_485_760,
    )
    supabase_place_photos_bucket: str = "place-photos"
    supabase_place_photo_max_bytes: int = Field(
        default=5_242_880,
        ge=1,
        le=20_971_520,
    )
    supabase_place_photos_max_per_place: int = Field(default=10, ge=1, le=30)
    supabase_lugar_fotos_bucket: str = "place-photos"
    supabase_lugar_foto_max_bytes: int = Field(
        default=5_242_880,
        ge=1,
        le=20_971_520,
    )
    supabase_lugar_fotos_max_por_lugar: int = Field(default=10, ge=1, le=30)

    infobip_api_key: str | None = None
    infobip_base_url: str = "https://55e4jx.api.infobip.com"
    infobip_timeout_seconds: float = Field(default=20.0, ge=1.0, le=120.0)
    infobip_whatsapp_from: str | None = None
    infobip_default_template_name: str = "test_whatsapp_template_en"
    infobip_default_language: str = "en"

    @field_validator(
        "openai_api_key",
        "google_maps_api_key",
        "supabase_url",
        "supabase_key",
        "supabase_service_role_key",
        "infobip_api_key",
        "infobip_whatsapp_from",
        mode="before",
    )
    @classmethod
    def empty_string_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def split_cors_origins(cls, value):  # type: ignore[no-untyped-def]
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            return [origin.strip() for origin in stripped.split(",") if origin.strip()]
        return value

    @property
    def is_openai_configured(self) -> bool:
        return self.openai_api_key is not None

    @property
    def is_google_places_configured(self) -> bool:
        return self.google_maps_api_key is not None

    @property
    def is_supabase_configured(self) -> bool:
        return self.supabase_url is not None and self.supabase_key is not None

    @property
    def is_infobip_configured(self) -> bool:
        return self.infobip_api_key is not None


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

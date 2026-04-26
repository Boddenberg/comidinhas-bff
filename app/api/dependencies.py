from fastapi import Depends, Request
import httpx

from app.core.config import Settings, get_settings
from app.integrations.google_places.client import GooglePlacesClient
from app.integrations.openai.client import OpenAIClient
from app.integrations.supabase.client import SupabaseClient
from app.modules.chat.use_cases import ChatWithOpenAIUseCase
from app.modules.google_places.use_cases import SearchNearbyRestaurantsUseCase
from app.modules.profiles.use_cases import ManageProfilesUseCase


def get_app_settings() -> Settings:
    return get_settings()


def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


def get_openai_client(
    http_client: httpx.AsyncClient = Depends(get_http_client),
    settings: Settings = Depends(get_app_settings),
) -> OpenAIClient:
    return OpenAIClient(http_client=http_client, settings=settings)


def get_chat_use_case(
    client: OpenAIClient = Depends(get_openai_client),
    settings: Settings = Depends(get_app_settings),
) -> ChatWithOpenAIUseCase:
    return ChatWithOpenAIUseCase(
        client=client,
        default_model=settings.openai_chat_model,
        default_system_prompt=settings.openai_system_prompt,
    )


def get_google_places_client(
    http_client: httpx.AsyncClient = Depends(get_http_client),
    settings: Settings = Depends(get_app_settings),
) -> GooglePlacesClient:
    return GooglePlacesClient(http_client=http_client, settings=settings)


def get_nearby_restaurants_use_case(
    client: GooglePlacesClient = Depends(get_google_places_client),
) -> SearchNearbyRestaurantsUseCase:
    return SearchNearbyRestaurantsUseCase(client=client)


def get_supabase_client(
    http_client: httpx.AsyncClient = Depends(get_http_client),
    settings: Settings = Depends(get_app_settings),
) -> SupabaseClient:
    return SupabaseClient(http_client=http_client, settings=settings)


def get_manage_profiles_use_case(
    client: SupabaseClient = Depends(get_supabase_client),
) -> ManageProfilesUseCase:
    return ManageProfilesUseCase(client=client)

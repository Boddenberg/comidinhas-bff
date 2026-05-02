from __future__ import annotations

from app.integrations.supabase.auth import SupabaseAuthMixin
from app.integrations.supabase.base import BaseSupabaseClient
from app.integrations.supabase.legacy_groups import SupabaseLegacyGroupsMixin
from app.integrations.supabase.legacy_places import SupabaseLegacyPlacesMixin
from app.integrations.supabase.no_auth_grupos import SupabaseNoAuthGruposMixin
from app.integrations.supabase.no_auth_guia_ai import SupabaseNoAuthGuiaAiMixin
from app.integrations.supabase.no_auth_guias import SupabaseNoAuthGuiasMixin
from app.integrations.supabase.no_auth_lugares import SupabaseNoAuthLugaresMixin
from app.integrations.supabase.no_auth_perfis import SupabaseNoAuthPerfisMixin
from app.integrations.supabase.rpc import SupabaseRpcMixin


class SupabaseClient(
    SupabaseNoAuthPerfisMixin,
    SupabaseNoAuthGruposMixin,
    SupabaseNoAuthLugaresMixin,
    SupabaseNoAuthGuiasMixin,
    SupabaseNoAuthGuiaAiMixin,
    SupabaseLegacyPlacesMixin,
    SupabaseLegacyGroupsMixin,
    SupabaseAuthMixin,
    SupabaseRpcMixin,
    BaseSupabaseClient,
):
    """Compatibility facade over focused Supabase adapters."""

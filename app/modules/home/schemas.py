from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.modules.groups.schemas import GroupMemberRole, GroupType
from app.modules.places.schemas import PlaceResponse, PlaceStatus


class HomeGroupMemberSummary(BaseModel):
    profile_id: str
    role: GroupMemberRole
    full_name: str | None = None
    username: str | None = None
    avatar_url: str | None = None


class HomeGroupSummary(BaseModel):
    id: str
    name: str
    type: GroupType
    description: str | None = None
    owner_id: str
    created_at: datetime | None = None
    members: list[HomeGroupMemberSummary] = Field(default_factory=list)


class HomeCounters(BaseModel):
    total_places: int = 0
    total_visited: int = 0
    total_favorites: int = 0
    total_want_to_go: int = 0


class HomeResponse(BaseModel):
    group: HomeGroupSummary
    counters: HomeCounters
    top_favorites: list[PlaceResponse] = Field(default_factory=list)
    latest_places: list[PlaceResponse] = Field(default_factory=list)
    want_to_go: list[PlaceResponse] = Field(default_factory=list)
    want_to_return: list[PlaceResponse] = Field(default_factory=list)


def _map_member(raw: Any) -> HomeGroupMemberSummary | None:
    if not isinstance(raw, dict):
        return None
    return HomeGroupMemberSummary(
        profile_id=str(raw.get("profile_id", "")),
        role=GroupMemberRole(raw.get("role") or GroupMemberRole.MEMBER.value),
        full_name=raw.get("full_name"),
        username=raw.get("username"),
        avatar_url=raw.get("avatar_url"),
    )


def _map_place(raw: Any) -> PlaceResponse | None:
    if not isinstance(raw, dict):
        return None
    return PlaceResponse(
        id=str(raw.get("id", "")),
        group_id=str(raw.get("group_id", "")),
        name=str(raw.get("name", "")),
        category=raw.get("category"),
        neighborhood=raw.get("neighborhood"),
        city=raw.get("city"),
        price_range=raw.get("price_range"),
        link=raw.get("link"),
        image_url=raw.get("image_url"),
        notes=raw.get("notes"),
        status=PlaceStatus(raw.get("status") or PlaceStatus.QUERO_IR.value),
        is_favorite=bool(raw.get("is_favorite") or False),
        created_by=str(raw.get("created_by", "")),
        updated_by=raw.get("updated_by"),
        created_at=raw.get("created_at"),
        updated_at=raw.get("updated_at"),
    )


def map_home_payload(payload: dict[str, Any]) -> HomeResponse:
    group_raw = payload.get("group") or {}
    if not isinstance(group_raw, dict):
        group_raw = {}

    members_raw = group_raw.get("members") or []
    members = [m for m in (_map_member(item) for item in members_raw) if m is not None]

    counters_raw = payload.get("counters") or {}
    counters = HomeCounters(
        total_places=int(counters_raw.get("total_places") or 0),
        total_visited=int(counters_raw.get("total_visited") or 0),
        total_favorites=int(counters_raw.get("total_favorites") or 0),
        total_want_to_go=int(counters_raw.get("total_want_to_go") or 0),
    )

    def _list(key: str) -> list[PlaceResponse]:
        items = payload.get(key) or []
        if not isinstance(items, list):
            return []
        return [p for p in (_map_place(item) for item in items) if p is not None]

    return HomeResponse(
        group=HomeGroupSummary(
            id=str(group_raw.get("id", "")),
            name=str(group_raw.get("name", "")),
            type=GroupType(group_raw.get("type") or GroupType.GROUP.value),
            description=group_raw.get("description"),
            owner_id=str(group_raw.get("owner_id", "")),
            created_at=group_raw.get("created_at"),
            members=members,
        ),
        counters=counters,
        top_favorites=_list("top_favorites"),
        latest_places=_list("latest_places"),
        want_to_go=_list("want_to_go"),
        want_to_return=_list("want_to_return"),
    )

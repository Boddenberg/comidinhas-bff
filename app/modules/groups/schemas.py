from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class GroupType(str, Enum):
    COUPLE = "couple"
    GROUP = "group"


class GroupMemberRole(str, Enum):
    OWNER = "owner"
    MEMBER = "member"


class GroupMemberResponse(BaseModel):
    profile_id: str
    role: GroupMemberRole
    full_name: str | None = None
    username: str | None = None
    avatar_url: str | None = None
    invited_by: str | None = None
    created_at: datetime | None = None


class GroupResponse(BaseModel):
    id: str
    name: str
    type: GroupType
    description: str | None = None
    owner_id: str
    created_by: str
    updated_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    members: list[GroupMemberResponse] = Field(default_factory=list)


class GroupSummaryResponse(BaseModel):
    id: str
    name: str
    type: GroupType
    description: str | None = None
    owner_id: str
    role: GroupMemberRole
    member_count: int = 0


class GroupListResponse(BaseModel):
    items: list[GroupSummaryResponse]


class GroupCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=80)
    type: GroupType = GroupType.COUPLE
    description: str | None = Field(default=None, max_length=500)
    partner_email: str | None = Field(default=None, min_length=5, max_length=255)
    partner_profile_id: str | None = Field(default=None, min_length=8, max_length=64)

    @field_validator("partner_email")
    @classmethod
    def normalize_partner_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        return normalized or None

    @model_validator(mode="after")
    def validate_partner_for_couple(self) -> "GroupCreateRequest":
        if self.type == GroupType.COUPLE and not (self.partner_email or self.partner_profile_id):
            raise ValueError(
                "Para criar um casal, informe partner_email ou partner_profile_id.",
            )
        return self


class GroupUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=80)
    type: GroupType | None = None
    description: str | None = Field(default=None, max_length=500)


class GroupMemberAddRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    profile_id: str | None = Field(default=None, min_length=8, max_length=64)
    email: str | None = Field(default=None, min_length=5, max_length=255)
    role: GroupMemberRole = GroupMemberRole.MEMBER

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        return normalized or None

    @model_validator(mode="after")
    def validate_identifier(self) -> "GroupMemberAddRequest":
        if not self.profile_id and not self.email:
            raise ValueError("Informe profile_id ou email do membro a adicionar.")
        return self


class SetActiveGroupRequest(BaseModel):
    group_id: str | None = Field(default=None, min_length=8, max_length=64)


class ProfileContextResponse(BaseModel):
    user_id: str
    profile_id: str
    email: str | None = None
    username: str | None = None
    full_name: str | None = None
    avatar_url: str | None = None
    active_group: GroupResponse | None = None
    active_role: GroupMemberRole | None = None
    groups: list[GroupSummaryResponse] = Field(default_factory=list)


class SeedFilipeVictorRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    filipe_email: str = Field(
        default="filipe@comidinhas.app",
        min_length=5,
        max_length=255,
    )
    victor_email: str = Field(
        default="victor@comidinhas.app",
        min_length=5,
        max_length=255,
    )

    @field_validator("filipe_email", "victor_email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class SeedFilipeVictorResponse(BaseModel):
    group_id: str
    message: str = "Casal Filipe e Victor configurado com sucesso."

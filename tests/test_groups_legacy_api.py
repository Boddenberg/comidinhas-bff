import pytest

from app.modules.groups.schemas import GroupMemberRole
from app.modules.groups.use_cases import ManageGroupsUseCase


class FakeLegacyGroupsClient:
    async def get_user(self, *, access_token):  # type: ignore[no-untyped-def]
        assert access_token == "access-token"
        return {
            "id": "user-1",
            "email": "ana@example.com",
            "user_metadata": {"username": "ana"},
        }

    async def get_profile(self, *, access_token, user_id):  # type: ignore[no-untyped-def]
        assert access_token == "access-token"
        assert user_id == "user-1"
        return {
            "id": "user-1",
            "email": "ana@example.com",
            "username": "ana",
            "full_name": "Ana Silva",
            "avatar_url": "https://example.com/avatar.png",
            "active_group_id": "group-1",
        }

    async def list_user_memberships(self, *, access_token, user_id):  # type: ignore[no-untyped-def]
        assert access_token == "access-token"
        assert user_id == "user-1"
        return [{"group_id": "group-1", "role": "owner"}]

    async def list_groups(self, *, access_token):  # type: ignore[no-untyped-def]
        assert access_token == "access-token"
        return [
            {
                "id": "group-1",
                "name": "Ana e Bia",
                "type": "couple",
                "description": None,
                "owner_id": "user-1",
            }
        ]

    async def get_group_with_members(self, *, access_token, group_id):  # type: ignore[no-untyped-def]
        assert access_token == "access-token"
        assert group_id == "group-1"
        return {
            "id": "group-1",
            "name": "Ana e Bia",
            "type": "couple",
            "description": None,
            "owner_id": "user-1",
            "created_by": "user-1",
            "members": [
                {
                    "profile_id": "user-1",
                    "role": "owner",
                    "profile": {
                        "id": "user-1",
                        "full_name": "Ana Silva",
                        "username": "ana",
                        "avatar_url": "https://example.com/avatar.png",
                    },
                }
            ],
        }


@pytest.mark.anyio
async def test_legacy_groups_context_uses_authenticated_contract() -> None:
    use_case = ManageGroupsUseCase(client=FakeLegacyGroupsClient())  # type: ignore[arg-type]

    response = await use_case.get_my_context(access_token="access-token")

    assert response.profile_id == "user-1"
    assert response.active_group is not None
    assert response.active_group.id == "group-1"
    assert response.active_role == GroupMemberRole.OWNER
    assert response.groups[0].role == GroupMemberRole.OWNER

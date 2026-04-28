import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_manage_guias_use_case
from app.core.errors import BadRequestError
from app.main import app
from app.modules.guias.schemas import (
    GuiaCreateRequest,
    GuiaListResponse,
    GuiaResponse,
)
from app.modules.guias.use_cases import ManageGuiasUseCase
from app.modules.lugares.schemas import LugarResponse, StatusLugar


def build_lugar(lugar_id: str, grupo_id: str, nome: str) -> dict:
    return {
        "id": lugar_id,
        "grupo_id": grupo_id,
        "nome": nome,
        "status": "quero_ir",
        "favorito": False,
        "fotos": [],
        "extra": {},
    }


class FakeGuiasClient:
    def __init__(self) -> None:
        self.groups = {"grupo-123": {"id": "grupo-123", "nome": "Filipe"}}
        self.places = {
            "lugar-001": build_lugar("lugar-001", "grupo-123", "Falafel da Esquina"),
            "lugar-002": build_lugar("lugar-002", "grupo-123", "Casa Arabe"),
            "lugar-999": build_lugar("lugar-999", "grupo-999", "Outro Grupo"),
        }
        self.guides: dict[str, dict] = {}

    async def get_grupo(self, *, grupo_id):  # type: ignore[no-untyped-def]
        return self.groups.get(grupo_id)

    async def get_lugar(self, *, lugar_id, select="*"):  # type: ignore[no-untyped-def]
        return self.places.get(lugar_id)

    async def list_guias(self, *, grupo_id):  # type: ignore[no-untyped-def]
        return [guide for guide in self.guides.values() if guide["grupo_id"] == grupo_id]

    async def get_guia(self, *, guia_id):  # type: ignore[no-untyped-def]
        return self.guides.get(guia_id)

    async def insert_guia(self, *, payload):  # type: ignore[no-untyped-def]
        guide = {"id": "guia-001", **payload}
        self.guides[guide["id"]] = guide
        return guide

    async def update_guia(self, *, guia_id, payload):  # type: ignore[no-untyped-def]
        self.guides[guia_id].update(payload)

    async def delete_guia(self, *, guia_id):  # type: ignore[no-untyped-def]
        self.guides.pop(guia_id, None)


@pytest.mark.anyio
async def test_criar_guia_com_lugares_do_mesmo_grupo() -> None:
    fake_client = FakeGuiasClient()
    use_case = ManageGuiasUseCase(client=fake_client)  # type: ignore[arg-type]

    response = await use_case.criar(
        request=GuiaCreateRequest(
            grupo_id="grupo-123",
            nome="Guia Arabe",
            lugar_ids=["lugar-001", "lugar-002", "lugar-001"],
        )
    )

    assert response.nome == "Guia Arabe"
    assert response.lugar_ids == ["lugar-001", "lugar-002"]
    assert [lugar.nome for lugar in response.lugares] == [
        "Falafel da Esquina",
        "Casa Arabe",
    ]
    assert response.total_lugares == 2


@pytest.mark.anyio
async def test_guia_rejeita_lugar_de_outro_grupo() -> None:
    fake_client = FakeGuiasClient()
    use_case = ManageGuiasUseCase(client=fake_client)  # type: ignore[arg-type]

    with pytest.raises(BadRequestError):
        await use_case.criar(
            request=GuiaCreateRequest(
                grupo_id="grupo-123",
                nome="Misturado",
                lugar_ids=["lugar-001", "lugar-999"],
            )
        )


class FakeGuiasUseCase:
    async def listar(self, *, grupo_id: str):  # type: ignore[no-untyped-def]
        assert grupo_id == "grupo-123"
        return GuiaListResponse(
            items=[
                GuiaResponse(
                    id="guia-001",
                    grupo_id="grupo-123",
                    nome="Guia Arabe",
                    lugar_ids=["lugar-001"],
                    lugares=[
                        LugarResponse(
                            id="lugar-001",
                            grupo_id="grupo-123",
                            nome="Falafel da Esquina",
                            status=StatusLugar.QUERO_IR,
                        )
                    ],
                    total_lugares=1,
                )
            ],
            total=1,
        )


def test_listar_guias_nao_exige_bearer_token() -> None:
    app.dependency_overrides[get_manage_guias_use_case] = lambda: FakeGuiasUseCase()

    with TestClient(app) as client:
        response = client.get("/api/v1/guias/?grupo_id=grupo-123")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["items"][0]["nome"] == "Guia Arabe"
    assert response.json()["items"][0]["lugares"][0]["nome"] == "Falafel da Esquina"

from fastapi.testclient import TestClient

import pytest

from app.api.dependencies import get_manage_grupos_use_case
from app.main import app
from app.modules.grupos.schemas import (
    GrupoCreateRequest,
    GrupoConviteResponse,
    GrupoListResponse,
    GrupoResponse,
    GrupoUpdateRequest,
    MembroSchema,
    PapelMembro,
    PapelMembroUpdateRequest,
    ResponderSolicitacaoGrupoRequest,
    SolicitacaoEntradaGrupoRequest,
    StatusSolicitacaoGrupo,
    TipoGrupo,
)
from app.modules.grupos.use_cases import ManageGruposUseCase
from app.modules.perfis.schemas import PerfilCreateRequest
from app.modules.perfis.use_cases import ManagePerfisUseCase
from app.core.errors import ConflictError, PermissionDeniedError


class FakePerfisClient:
    def __init__(self) -> None:
        self.inserted_group: dict | None = None
        self.updated_profile: dict | None = None

    async def insert_perfil(self, *, payload):  # type: ignore[no-untyped-def]
        return {"id": "perfil-1", **payload}

    async def insert_grupo(self, *, payload):  # type: ignore[no-untyped-def]
        self.inserted_group = payload
        return {"id": "grupo-individual-1", **payload}

    async def update_perfil(self, *, perfil_id, payload):  # type: ignore[no-untyped-def]
        self.updated_profile = {"perfil_id": perfil_id, "payload": payload}


class FakePerfilDuplicadoClient(FakePerfisClient):
    async def insert_perfil(self, *, payload):  # type: ignore[no-untyped-def]
        raise ConflictError("duplicate key value violates unique constraint")

    async def get_perfil_por_email(self, *, email):  # type: ignore[no-untyped-def]
        return {
            "id": "perfil-existente",
            "nome": "Victor",
            "email": email,
            "grupo_individual_id": None,
        }


@pytest.mark.anyio
async def test_criar_perfil_tambem_cria_espaco_individual() -> None:
    fake_client = FakePerfisClient()
    use_case = ManagePerfisUseCase(client=fake_client)  # type: ignore[arg-type]

    response = await use_case.criar(
        request=PerfilCreateRequest(nome="Filipe", email="FILIPE@example.com")
    )

    assert response.grupo_individual_id == "grupo-individual-1"
    assert response.email == "filipe@example.com"
    assert fake_client.inserted_group == {
        "nome": "Filipe",
        "tipo": "individual",
        "descricao": None,
        "dono_perfil_id": "perfil-1",
        "membros": [
            {
                "perfil_id": "perfil-1",
                "nome": "Filipe",
                "email": "filipe@example.com",
                "papel": "dono",
            }
        ],
    }
    assert fake_client.updated_profile == {
        "perfil_id": "perfil-1",
        "payload": {"grupo_individual_id": "grupo-individual-1"},
    }


@pytest.mark.anyio
async def test_criar_perfil_recupera_tentativa_anterior_com_email_duplicado() -> None:
    fake_client = FakePerfilDuplicadoClient()
    use_case = ManagePerfisUseCase(client=fake_client)  # type: ignore[arg-type]

    response = await use_case.criar(
        request=PerfilCreateRequest(nome="Victor", email="victor@example.com")
    )

    assert response.id == "perfil-existente"
    assert response.grupo_individual_id == "grupo-individual-1"
    assert fake_client.inserted_group is not None
    assert fake_client.inserted_group["tipo"] == "individual"
    assert fake_client.inserted_group["dono_perfil_id"] == "perfil-existente"
    assert fake_client.updated_profile == {
        "perfil_id": "perfil-existente",
        "payload": {"grupo_individual_id": "grupo-individual-1"},
    }


class FakeGruposClient:
    def __init__(self) -> None:
        self.inserted_group: dict | None = None
        self.updated_group: dict | None = None
        self.profiles = {
            "perfil-filipe": {
                "id": "perfil-filipe",
                "nome": "Filipe",
                "email": "filipe@example.com",
            },
            "perfil-victor": {
                "id": "perfil-victor",
                "nome": "Victor",
                "email": "victor@example.com",
            },
        }
        self.groups: dict[str, dict] = {}

    async def list_grupos(self, *, perfil_id=None):  # type: ignore[no-untyped-def]
        return []

    async def get_perfil(self, *, perfil_id):  # type: ignore[no-untyped-def]
        return self.profiles.get(perfil_id)

    async def get_perfil_por_email(self, *, email):  # type: ignore[no-untyped-def]
        return next(
            (p for p in self.profiles.values() if p["email"] == email),
            None,
        )

    async def get_grupo(self, *, grupo_id):  # type: ignore[no-untyped-def]
        return self.groups.get(grupo_id)

    async def get_grupo_por_codigo(self, *, codigo):  # type: ignore[no-untyped-def]
        return next((g for g in self.groups.values() if g.get("codigo") == codigo), None)

    async def insert_grupo(self, *, payload):  # type: ignore[no-untyped-def]
        self.inserted_group = payload
        grupo = {"id": "grupo-casal-1", "solicitacoes": [], **payload}
        self.groups[grupo["id"]] = grupo
        return grupo

    async def update_grupo(self, *, grupo_id, payload):  # type: ignore[no-untyped-def]
        self.updated_group = {"grupo_id": grupo_id, "payload": payload}
        self.groups[grupo_id].update(payload)


@pytest.mark.anyio
async def test_criar_casal_resolve_membros_por_perfil_ou_email() -> None:
    fake_client = FakeGruposClient()
    use_case = ManageGruposUseCase(client=fake_client)  # type: ignore[arg-type]

    response = await use_case.criar(
        request=GrupoCreateRequest(
            nome="Filipe e Victor",
            tipo=TipoGrupo.CASAL,
            membros=[
                MembroSchema(perfil_id="perfil-filipe"),
                MembroSchema(email="victor@example.com"),
            ],
        )
    )

    assert response.id == "grupo-casal-1"
    assert response.tipo == TipoGrupo.CASAL
    assert fake_client.inserted_group is not None
    assert len(fake_client.inserted_group["codigo"]) == 6
    assert fake_client.inserted_group["codigo"].isdigit()
    assert fake_client.inserted_group["dono_perfil_id"] == "perfil-filipe"
    assert fake_client.inserted_group["foto_url"] is None
    assert fake_client.inserted_group["membros"] == [
        {
            "perfil_id": "perfil-filipe",
            "nome": "Filipe",
            "email": "filipe@example.com",
            "papel": "dono",
        },
        {
            "perfil_id": "perfil-victor",
            "nome": "Victor",
            "email": "victor@example.com",
            "papel": "membro",
        },
    ]


@pytest.mark.anyio
async def test_criar_grupo_gera_codigo_e_define_dono() -> None:
    fake_client = FakeGruposClient()
    use_case = ManageGruposUseCase(client=fake_client)  # type: ignore[arg-type]

    response = await use_case.criar(
        request=GrupoCreateRequest(
            nome="Roles de comida",
            tipo=TipoGrupo.GRUPO,
            dono_perfil_id="perfil-filipe",
        )
    )

    assert response.codigo is not None
    assert len(response.codigo) == 6
    assert response.codigo.isdigit()
    assert response.membros[0].perfil_id == "perfil-filipe"
    assert response.membros[0].papel == PapelMembro.DONO


@pytest.mark.anyio
async def test_solicitar_entrada_por_codigo_fica_pendente() -> None:
    fake_client = FakeGruposClient()
    fake_client.groups["grupo-123"] = {
        "id": "grupo-123",
        "codigo": "123456",
        "nome": "Roles",
        "tipo": "grupo",
        "dono_perfil_id": "perfil-filipe",
        "membros": [
            {
                "perfil_id": "perfil-filipe",
                "nome": "Filipe",
                "email": "filipe@example.com",
                "papel": "dono",
            }
        ],
        "solicitacoes": [],
    }
    use_case = ManageGruposUseCase(client=fake_client)  # type: ignore[arg-type]

    response = await use_case.solicitar_entrada(
        codigo="123456",
        request=SolicitacaoEntradaGrupoRequest(
            perfil_id="perfil-victor",
            mensagem="Quero entrar!",
        ),
    )

    assert response.status == StatusSolicitacaoGrupo.PENDENTE
    assert response.perfil_id == "perfil-victor"
    assert fake_client.updated_group is not None
    assert fake_client.updated_group["payload"]["solicitacoes"][0]["status"] == "pendente"
    assert "perfil-victor" not in [
        membro["perfil_id"] for membro in fake_client.groups["grupo-123"]["membros"]
    ]


@pytest.mark.anyio
async def test_gerar_convite_retorna_link_mensagem_e_payload_qr_code() -> None:
    fake_client = FakeGruposClient()
    fake_client.groups["grupo-123"] = {
        "id": "grupo-123",
        "codigo": "123456",
        "nome": "Roles",
        "tipo": "grupo",
        "dono_perfil_id": "perfil-filipe",
        "membros": [
            {
                "perfil_id": "perfil-filipe",
                "nome": "Filipe",
                "email": "filipe@example.com",
                "papel": "dono",
            },
            {
                "perfil_id": "perfil-victor",
                "nome": "Victor",
                "email": "victor@example.com",
                "papel": "membro",
            },
        ],
        "solicitacoes": [],
    }
    use_case = ManageGruposUseCase(
        client=fake_client,  # type: ignore[arg-type]
        web_app_base_url="https://comidinhas-web-production.up.railway.app",
        web_group_invite_path="/entrar",
    )

    response = await use_case.gerar_convite(
        grupo_id="grupo-123",
        responsavel_perfil_id="perfil-victor",
    )

    assert response.grupo_id == "grupo-123"
    assert response.grupo_nome == "Roles"
    assert response.codigo == "123456"
    assert response.url == "https://comidinhas-web-production.up.railway.app/entrar?codigo=123456"
    assert response.qr_code_payload == response.url
    assert response.mensagem == (
        "Bora entrar no meu grupo Roles no Comidinhas?\n\n"
        "Acesse: https://comidinhas-web-production.up.railway.app/entrar?codigo=123456\n"
        "Codigo do grupo: 123456"
    )


@pytest.mark.anyio
async def test_gerar_convite_cria_codigo_para_grupo_antigo_sem_codigo() -> None:
    fake_client = FakeGruposClient()
    fake_client.groups["grupo-123"] = {
        "id": "grupo-123",
        "nome": "Roles",
        "tipo": "grupo",
        "dono_perfil_id": "perfil-filipe",
        "membros": [
            {
                "perfil_id": "perfil-filipe",
                "nome": "Filipe",
                "email": "filipe@example.com",
                "papel": "dono",
            }
        ],
        "solicitacoes": [],
    }
    use_case = ManageGruposUseCase(client=fake_client)  # type: ignore[arg-type]

    response = await use_case.gerar_convite(
        grupo_id="grupo-123",
        responsavel_perfil_id="perfil-filipe",
    )

    assert len(response.codigo) == 6
    assert response.codigo.isdigit()
    assert fake_client.updated_group is not None
    assert fake_client.updated_group["payload"] == {"codigo": response.codigo}


@pytest.mark.anyio
async def test_dono_aceita_solicitacao_e_membro_entra_no_grupo() -> None:
    fake_client = FakeGruposClient()
    fake_client.groups["grupo-123"] = {
        "id": "grupo-123",
        "codigo": "123456",
        "nome": "Roles",
        "tipo": "grupo",
        "dono_perfil_id": "perfil-filipe",
        "membros": [
            {
                "perfil_id": "perfil-filipe",
                "nome": "Filipe",
                "email": "filipe@example.com",
                "papel": "dono",
            }
        ],
        "solicitacoes": [
            {
                "id": "solicitacao-1",
                "perfil_id": "perfil-victor",
                "nome": "Victor",
                "email": "victor@example.com",
                "status": "pendente",
                "solicitado_em": "2026-04-28T12:00:00+00:00",
            }
        ],
    }
    use_case = ManageGruposUseCase(client=fake_client)  # type: ignore[arg-type]

    response = await use_case.aceitar_solicitacao(
        grupo_id="grupo-123",
        solicitacao_id="solicitacao-1",
        request=ResponderSolicitacaoGrupoRequest(responsavel_perfil_id="perfil-filipe"),
    )

    assert any(m.perfil_id == "perfil-victor" for m in response.membros)
    assert response.solicitacoes[0].status == StatusSolicitacaoGrupo.ACEITA


@pytest.mark.anyio
async def test_administrador_edita_infos_mas_nao_define_papeis() -> None:
    fake_client = FakeGruposClient()
    fake_client.groups["grupo-123"] = {
        "id": "grupo-123",
        "codigo": "123456",
        "nome": "Roles",
        "tipo": "grupo",
        "dono_perfil_id": "perfil-filipe",
        "membros": [
            {
                "perfil_id": "perfil-filipe",
                "nome": "Filipe",
                "email": "filipe@example.com",
                "papel": "dono",
            },
            {
                "perfil_id": "perfil-victor",
                "nome": "Victor",
                "email": "victor@example.com",
                "papel": "administrador",
            },
        ],
        "solicitacoes": [],
    }
    use_case = ManageGruposUseCase(client=fake_client)  # type: ignore[arg-type]

    response = await use_case.atualizar(
        grupo_id="grupo-123",
        request=GrupoUpdateRequest(
            nome="Roles oficiais",
            responsavel_perfil_id="perfil-victor",
        ),
    )

    assert response.nome == "Roles oficiais"

    with pytest.raises(PermissionDeniedError):
        await use_case.definir_papel_membro(
            grupo_id="grupo-123",
            perfil_id="perfil-victor",
            request=PapelMembroUpdateRequest(
                papel=PapelMembro.MEMBRO,
                responsavel_perfil_id="perfil-victor",
            ),
        )


@pytest.mark.anyio
async def test_atualizar_fundo_resolve_grupo_legado_por_email() -> None:
    fake_client = FakeGruposClient()
    fake_client.groups["grupo-legado"] = {
        "id": "grupo-legado",
        "codigo": "123456",
        "nome": "Casal de filipe",
        "tipo": "casal",
        "dono_perfil_id": None,
        "membros": [
            {
                "nome": "filipe",
                "email": "filipe@example.com",
                "papel": "membro",
            }
        ],
        "solicitacoes": [],
    }
    use_case = ManageGruposUseCase(client=fake_client)  # type: ignore[arg-type]

    response = await use_case.atualizar(
        grupo_id="grupo-legado",
        request=GrupoUpdateRequest(
            foto_url="fotos-grupo/fundo.png",
            responsavel_perfil_id="perfil-filipe",
        ),
    )

    assert response.foto_url == "fotos-grupo/fundo.png"
    assert response.dono_perfil_id == "perfil-filipe"
    assert response.membros[0].perfil_id == "perfil-filipe"
    assert response.membros[0].papel == PapelMembro.DONO


@pytest.mark.anyio
async def test_gerar_convite_resolve_grupo_legado_por_email() -> None:
    fake_client = FakeGruposClient()
    fake_client.groups["grupo-legado"] = {
        "id": "grupo-legado",
        "codigo": "123456",
        "nome": "Casal de filipe",
        "tipo": "casal",
        "dono_perfil_id": None,
        "membros": [
            {
                "nome": "filipe",
                "email": "filipe@example.com",
                "papel": "membro",
            }
        ],
        "solicitacoes": [],
    }
    use_case = ManageGruposUseCase(client=fake_client)  # type: ignore[arg-type]

    response = await use_case.gerar_convite(
        grupo_id="grupo-legado",
        responsavel_perfil_id="perfil-filipe",
    )

    assert response.codigo == "123456"
    assert fake_client.groups["grupo-legado"]["dono_perfil_id"] == "perfil-filipe"
    assert fake_client.groups["grupo-legado"]["membros"][0]["perfil_id"] == "perfil-filipe"


class FakeContextosUseCase:
    async def listar(self, *, perfil_id: str | None = None):  # type: ignore[no-untyped-def]
        assert perfil_id == "perfil-1"
        return GrupoListResponse(
            items=[
                GrupoResponse(
                    id="grupo-individual-1",
                    nome="Filipe",
                    tipo=TipoGrupo.INDIVIDUAL,
                    dono_perfil_id="perfil-1",
                    membros=[
                        MembroSchema(
                            perfil_id="perfil-1",
                            nome="Filipe",
                            email="filipe@example.com",
                            papel="dono",
                        )
                    ],
                )
            ],
            total=1,
        )


class FakeConviteUseCase:
    async def gerar_convite(self, *, grupo_id, responsavel_perfil_id):  # type: ignore[no-untyped-def]
        assert grupo_id == "grupo-123"
        assert responsavel_perfil_id == "perfil-1"
        return GrupoConviteResponse(
            grupo_id=grupo_id,
            grupo_nome="Roles",
            codigo="123456",
            url="https://comidinhas-web-production.up.railway.app/entrar?codigo=123456",
            qr_code_payload="https://comidinhas-web-production.up.railway.app/entrar?codigo=123456",
            mensagem="Bora entrar no meu grupo Roles no Comidinhas?",
        )


def test_contextos_do_perfil_nao_exige_bearer_token() -> None:
    app.dependency_overrides[get_manage_grupos_use_case] = lambda: FakeContextosUseCase()

    with TestClient(app) as client:
        response = client.get("/api/v1/perfis/perfil-1/contextos")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["items"][0]["tipo"] == "individual"
    assert response.json()["items"][0]["membros"][0]["perfil_id"] == "perfil-1"


def test_endpoint_convite_retorna_link_para_compartilhar() -> None:
    app.dependency_overrides[get_manage_grupos_use_case] = lambda: FakeConviteUseCase()

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/grupos/grupo-123/convite",
            params={"responsavel_perfil_id": "perfil-1"},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["url"] == "https://comidinhas-web-production.up.railway.app/entrar?codigo=123456"
    assert response.json()["qr_code_payload"] == response.json()["url"]

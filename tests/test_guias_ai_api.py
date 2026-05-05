from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.dependencies import get_guias_ai_use_case
from app.core.config import Settings
from app.core.errors import BadRequestError
from app.main import app
from app.modules.guias_ai.schemas import (
    CriarGuiaIaRequest,
    JobResponse,
    JobStatus,
)
from app.modules.guias_ai.use_cases import GuiasAiUseCase


class FakeGuiasAiUseCase:
    async def criar_job(self, *, request):  # type: ignore[no-untyped-def]
        assert request.grupo_id == "grupo-123"
        assert len(request.texto) == 1001
        return JobResponse(
            id="job-123",
            grupo_id=request.grupo_id,
            perfil_id=request.perfil_id,
            status=JobStatus.CREATED,
            progresso_percentual=1,
        )


class FakeSupabaseClient:
    async def get_grupo(self, *, grupo_id):  # type: ignore[no-untyped-def]
        return {"id": grupo_id}


class FakeSupabaseClientWithActiveJob:
    def __init__(self) -> None:
        self.count_active_called = False
        self.insert_called = False

    async def get_grupo(self, *, grupo_id):  # type: ignore[no-untyped-def]
        return {"id": grupo_id}

    async def get_guia_ai_job_by_hash(self, *, grupo_id, texto_hash):  # type: ignore[no-untyped-def]
        return {
            "id": "job-active-123",
            "grupo_id": grupo_id,
            "perfil_id": None,
            "status": JobStatus.ENRICHING_PLACES.value,
            "progresso_percentual": 76,
            "criado_em": datetime.now(timezone.utc).isoformat(),
            "estatisticas": {},
        }

    async def count_active_guia_ai_jobs(self, **kwargs):  # type: ignore[no-untyped-def]
        self.count_active_called = True
        return 99

    async def insert_guia_ai_job(self, *, payload):  # type: ignore[no-untyped-def]
        self.insert_called = True
        raise AssertionError("duplicate active imports should reuse the existing job")


def test_criar_guia_ia_route_aceita_texto_maior_que_mil_caracteres() -> None:
    app.dependency_overrides[get_guias_ai_use_case] = lambda: FakeGuiasAiUseCase()

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/guias/ia/imports",
            json={
                "grupo_id": "grupo-123",
                "texto": "x" * 1001,
            },
        )

    app.dependency_overrides.clear()

    assert response.status_code == 202
    assert response.json()["id"] == "job-123"


def test_criar_guia_ia_schema_aceita_ate_quatrocentos_mil_caracteres() -> None:
    request = CriarGuiaIaRequest(grupo_id="grupo-123", texto="x" * 400_000)

    assert len(request.texto) == 400_000


def test_criar_guia_ia_schema_rejeita_acima_de_quatrocentos_mil_caracteres() -> None:
    with pytest.raises(ValidationError):
        CriarGuiaIaRequest(grupo_id="grupo-123", texto="x" * 400_001)


@pytest.mark.anyio
async def test_criar_guia_ia_respeita_limite_configurado_sem_truncar() -> None:
    use_case = GuiasAiUseCase(
        settings=Settings(
            openai_api_key="test-token",
            guias_ai_text_max_chars=1000,
        ),
        supabase_client=FakeSupabaseClient(),  # type: ignore[arg-type]
        openai_client=object(),  # type: ignore[arg-type]
        google_places_client=object(),  # type: ignore[arg-type]
    )

    with pytest.raises(BadRequestError):
        await use_case.criar_job(
            request=CriarGuiaIaRequest(
                grupo_id="grupo-123",
                texto="x" * 1001,
            )
        )


@pytest.mark.anyio
async def test_criar_guia_ia_reusa_job_ativo_com_mesmo_texto() -> None:
    supabase = FakeSupabaseClientWithActiveJob()
    use_case = GuiasAiUseCase(
        settings=Settings(openai_api_key="test-token"),
        supabase_client=supabase,  # type: ignore[arg-type]
        openai_client=object(),  # type: ignore[arg-type]
        google_places_client=object(),  # type: ignore[arg-type]
    )

    response = await use_case.criar_job(
        request=CriarGuiaIaRequest(
            grupo_id="grupo-123",
            texto="restaurante " * 20,
        )
    )

    assert response.id == "job-active-123"
    assert supabase.count_active_called is False
    assert supabase.insert_called is False

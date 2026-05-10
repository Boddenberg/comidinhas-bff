"""Testes do mecanismo de historico das sugestoes da IA.

Cobre:
- carregar_contexto: leitura best-effort + parse de timestamps;
- HistoricoContexto: janelas de 24h e 7d, sinais de personalizacao;
- registrar_sugestoes: payload normalizado, ignora linhas invalidas,
  silencia falhas do Supabase;
- integracao com DecidirRestauranteUseCase: candidatos do dia/semana
  sao excluidos, fallback quando esvazia, prompt enriquecido com
  historico e sugestoes persistidas apos a escolha.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.decisoes import historico
from app.modules.decisoes.historico import HistoricoContexto, HistoricoSugestao
from app.modules.decisoes.schemas import DecidirRestauranteRequest, EscopoDecisao
from app.modules.decisoes.use_cases import DecidirRestauranteUseCase


def _row(
    *,
    nome: str,
    lugar_id: str | None = None,
    google_place_id: str | None = None,
    horas_atras: float = 1,
    posicao: int = 1,
    fonte: str = "decidir_restaurante",
    criterios: dict | None = None,
    motivo: str | None = "Otimo lugar",
) -> dict:
    criado = datetime.now(timezone.utc) - timedelta(hours=horas_atras)
    return {
        "lugar_id": lugar_id,
        "google_place_id": google_place_id,
        "nome": nome,
        "fonte": fonte,
        "posicao": posicao,
        "criterios": criterios or {},
        "motivo": motivo,
        "criado_em": criado.isoformat(),
    }


def _ctx(rows: list[dict]) -> HistoricoContexto:
    sugestoes = [HistoricoSugestao.from_row(row) for row in rows]
    return HistoricoContexto(sugestoes=sugestoes, agora=datetime.now(timezone.utc))


def test_janela_24h_marca_lugar_como_evitar() -> None:
    contexto = _ctx([_row(nome="Caro", lugar_id="L1", horas_atras=2)])

    assert contexto.lugares_evitar_dia() == {"L1"}
    assert contexto.lugares_evitar_semana() == {"L1"}


def test_janela_dia_ignora_linhas_antigas() -> None:
    contexto = _ctx([_row(nome="Velho", lugar_id="L1", horas_atras=72)])

    assert contexto.lugares_evitar_dia() == set()
    assert contexto.lugares_evitar_semana() == {"L1"}


def test_janela_semana_so_considera_escolha_principal() -> None:
    contexto = _ctx(
        [
            _row(nome="Alt", lugar_id="L1", posicao=2, horas_atras=48),
            _row(nome="Esc", lugar_id="L2", posicao=1, horas_atras=48),
        ]
    )

    assert contexto.lugares_evitar_semana() == {"L2"}


def test_janela_dia_considera_alternativas() -> None:
    contexto = _ctx([_row(nome="Alt", lugar_id="L1", posicao=2, horas_atras=2)])

    assert contexto.lugares_evitar_dia() == {"L1"}


def test_google_evitar_funciona_para_today() -> None:
    contexto = _ctx(
        [_row(nome="G", google_place_id="g-1", horas_atras=3, fonte="today_recommendations")]
    )

    assert contexto.google_evitar_dia() == {"g-1"}


def test_resumo_personalizacao_agrega_cozinhas_e_moods() -> None:
    contexto = _ctx(
        [
            _row(nome="A", lugar_id="L1", horas_atras=1, criterios={"mood": "romantico", "cozinhas": ["italiana"]}),
            _row(nome="B", lugar_id="L2", horas_atras=24, criterios={"mood": "romantico", "cozinhas": ["italiana", "japonesa"]}),
            _row(nome="C", lugar_id="L3", horas_atras=24 * 31, criterios={"mood": "antigo"}),
        ]
    )

    resumo = contexto.resumo_personalizacao()

    assert resumo["total_sugestoes_30d"] == 2
    assert "italiana" in resumo["cozinhas_frequentes"]
    assert "romantico" in resumo["moods_frequentes"]
    assert "antigo" not in resumo["moods_frequentes"]


@pytest.mark.anyio
async def test_carregar_contexto_silencia_falha_de_supabase() -> None:
    class Quebrado:
        async def list_sugestoes_ia_recentes(self, **_kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("indisponivel")

    contexto = await historico.carregar_contexto(supabase_client=Quebrado(), grupo_id="g")

    assert contexto.sugestoes == []


@pytest.mark.anyio
async def test_registrar_sugestoes_persiste_payload_normalizado() -> None:
    class Captura:
        def __init__(self) -> None:
            self.rows: list[dict] = []

        async def insert_sugestoes_ia(self, *, rows):  # type: ignore[no-untyped-def]
            self.rows = rows
            return rows

    capt = Captura()
    await historico.registrar_sugestoes(
        supabase_client=capt,
        grupo_id="grupo-123",
        perfil_id="perfil-1",
        fonte="decidir_restaurante",
        modelo="m",
        criterios={"mood": "feliz"},
        sugestoes=[
            {"nome": "A", "lugar_id": "L1", "motivo": "Especial pra voces"},
            {"nome": "B", "google_place_id": "g-2"},
            {"nome": "Sem id"},  # ignorada
        ],
    )

    assert len(capt.rows) == 2
    assert capt.rows[0]["posicao"] == 1
    assert capt.rows[0]["origem"] == "comidinhas"
    assert capt.rows[0]["motivo"] == "Especial pra voces"
    assert capt.rows[1]["posicao"] == 2
    assert capt.rows[1]["origem"] == "google"
    assert capt.rows[0]["criterios"] == {"mood": "feliz"}


@pytest.mark.anyio
async def test_registrar_sugestoes_silencia_falha_de_persistencia() -> None:
    class Quebrado:
        async def insert_sugestoes_ia(self, *, rows):  # type: ignore[no-untyped-def]
            raise RuntimeError("falha")

    # Nao levanta excecao, e melhor falhar silencioso do que quebrar a UX.
    await historico.registrar_sugestoes(
        supabase_client=Quebrado(),
        grupo_id="grupo-123",
        perfil_id=None,
        fonte="decidir_restaurante",
        modelo="m",
        criterios={},
        sugestoes=[{"nome": "X", "lugar_id": "L1"}],
    )


# --- Integracao com DecidirRestauranteUseCase ----------------------------


def _build_lugar(lugar_id: str, *, nome: str, status: str = "quero_ir") -> dict:
    return {
        "id": lugar_id,
        "grupo_id": "grupo-123",
        "nome": nome,
        "categoria": "Restaurante",
        "bairro": "Centro",
        "cidade": "Sao Paulo",
        "faixa_preco": 2,
        "status": status,
        "favorito": False,
        "notas": "",
        "fotos": [],
        "extra": {},
    }


class _FakeOpenAI:
    def __init__(self, lugar_id: str) -> None:
        self.lugar_id = lugar_id
        self.last_prompt = ""

    async def chat(self, *, prompt, system_prompt, model):  # type: ignore[no-untyped-def]
        self.last_prompt = prompt
        return json.dumps(
            {
                "escolha": {
                    "lugar_id": self.lugar_id,
                    "motivo": "Hoje pede algo aconchegante e este lugar combina com voces.",
                    "pontos_fortes": ["massa fresca"],
                    "ressalvas": [],
                    "confianca": 0.9,
                },
                "alternativas": [],
            }
        )


class _FakeSupabaseDecidir:
    def __init__(self, *, historico_rows: list[dict] | None = None) -> None:
        self.places = {
            "L1": _build_lugar("L1", nome="Italiano A"),
            "L2": _build_lugar("L2", nome="Italiano B"),
            "L3": _build_lugar("L3", nome="Italiano C"),
        }
        self._historico = historico_rows or []
        self.persisted: list[dict] = []

    async def get_grupo(self, *, grupo_id):  # type: ignore[no-untyped-def]
        return {"id": grupo_id}

    async def list_lugares(self, **kwargs):  # type: ignore[no-untyped-def]
        rows = list(self.places.values())
        return rows[: kwargs["page_size"]], len(rows)

    async def list_sugestoes_ia_recentes(self, **_kwargs):  # type: ignore[no-untyped-def]
        return self._historico

    async def insert_sugestoes_ia(self, *, rows):  # type: ignore[no-untyped-def]
        self.persisted.extend(rows)
        return rows


@pytest.mark.anyio
async def test_decidir_restaurante_exclui_lugar_sugerido_no_dia() -> None:
    fake_supabase = _FakeSupabaseDecidir(
        historico_rows=[_row(nome="Italiano A", lugar_id="L1", horas_atras=2)]
    )
    fake_openai = _FakeOpenAI(lugar_id="L2")
    use_case = DecidirRestauranteUseCase(
        openai_client=fake_openai,  # type: ignore[arg-type]
        supabase_client=fake_supabase,  # type: ignore[arg-type]
        model="fake",
    )

    response = await use_case.execute(
        request=DecidirRestauranteRequest(
            grupo_id="grupo-123",
            escopo=EscopoDecisao.TODOS,
            criterios={"mood": "aconchegante"},
        )
    )

    assert response.escolha.lugar.id == "L2"
    assert response.total_candidatos == 2  # L1 ficou de fora
    prompt_payload = json.loads(fake_openai.last_prompt)
    candidato_ids = {c["id"] for c in prompt_payload["candidatos"]}
    assert "L1" not in candidato_ids
    assert "Italiano A" in prompt_payload["historico"]["ultimas"]


@pytest.mark.anyio
async def test_decidir_restaurante_exclui_lugar_sugerido_na_semana() -> None:
    fake_supabase = _FakeSupabaseDecidir(
        historico_rows=[_row(nome="Italiano A", lugar_id="L1", horas_atras=72)]
    )
    use_case = DecidirRestauranteUseCase(
        openai_client=_FakeOpenAI(lugar_id="L2"),  # type: ignore[arg-type]
        supabase_client=fake_supabase,  # type: ignore[arg-type]
        model="fake",
    )

    response = await use_case.execute(
        request=DecidirRestauranteRequest(
            grupo_id="grupo-123",
            escopo=EscopoDecisao.TODOS,
        )
    )

    assert response.escolha.lugar.id == "L2"
    assert response.total_candidatos == 2


@pytest.mark.anyio
async def test_decidir_restaurante_relaxa_semana_quando_zera() -> None:
    fake_supabase = _FakeSupabaseDecidir(
        historico_rows=[
            _row(nome="A", lugar_id="L1", horas_atras=72),
            _row(nome="B", lugar_id="L2", horas_atras=72),
            _row(nome="C", lugar_id="L3", horas_atras=72),
        ]
    )
    use_case = DecidirRestauranteUseCase(
        openai_client=_FakeOpenAI(lugar_id="L1"),  # type: ignore[arg-type]
        supabase_client=fake_supabase,  # type: ignore[arg-type]
        model="fake",
    )

    response = await use_case.execute(
        request=DecidirRestauranteRequest(
            grupo_id="grupo-123",
            escopo=EscopoDecisao.TODOS,
        )
    )

    # Sem alternativa: cai pra escolher do que existe (relaxando a semana).
    assert response.escolha.lugar.id == "L1"


@pytest.mark.anyio
async def test_decidir_restaurante_persiste_escolha_no_historico() -> None:
    fake_supabase = _FakeSupabaseDecidir()
    use_case = DecidirRestauranteUseCase(
        openai_client=_FakeOpenAI(lugar_id="L2"),  # type: ignore[arg-type]
        supabase_client=fake_supabase,  # type: ignore[arg-type]
        model="fake",
    )

    await use_case.execute(
        request=DecidirRestauranteRequest(
            grupo_id="grupo-123",
            perfil_id="perfil-1",
            escopo=EscopoDecisao.TODOS,
            criterios={"mood": "aconchegante"},
        )
    )

    assert len(fake_supabase.persisted) == 1
    row = fake_supabase.persisted[0]
    assert row["lugar_id"] == "L2"
    assert row["fonte"] == "decidir_restaurante"
    assert row["perfil_id"] == "perfil-1"
    assert row["criterios"]["mood"] == "aconchegante"
    assert isinstance(row["motivo"], str) and row["motivo"]


@pytest.mark.anyio
async def test_decidir_restaurante_segue_funcionando_sem_supabase_de_historico() -> None:
    # Versao "antiga" do client que nao implementa as novas chamadas.
    class FakeAntigo:
        def __init__(self) -> None:
            self.places = {"L1": _build_lugar("L1", nome="Italiano A")}

        async def get_grupo(self, *, grupo_id):  # type: ignore[no-untyped-def]
            return {"id": grupo_id}

        async def list_lugares(self, **kwargs):  # type: ignore[no-untyped-def]
            rows = list(self.places.values())
            return rows[: kwargs["page_size"]], len(rows)

    use_case = DecidirRestauranteUseCase(
        openai_client=_FakeOpenAI(lugar_id="L1"),  # type: ignore[arg-type]
        supabase_client=FakeAntigo(),  # type: ignore[arg-type]
        model="fake",
    )

    response = await use_case.execute(
        request=DecidirRestauranteRequest(
            grupo_id="grupo-123",
            escopo=EscopoDecisao.TODOS,
        )
    )

    assert response.escolha.lugar.id == "L1"

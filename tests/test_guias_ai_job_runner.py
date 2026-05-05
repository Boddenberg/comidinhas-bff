import pytest

from app.core.config import Settings
from app.modules.guias_ai.job_runner import JobRunner
from app.modules.guias_ai.schemas import EnrichedItem, ExtractedRestaurant, StatusMatching


def test_internal_match_payload_preserves_maps_link_and_cover_photo() -> None:
    restaurant = ExtractedRestaurant(
        ordem=0,
        nome_original="Grindhouse Braserito",
        nome_normalizado="grindhouse braserito",
    )
    internal_lugar = {
        "id": "lugar-grindhouse",
        "nome": "Grindhouse Braserito",
        "bairro": "Pinheiros",
        "cidade": "Sao Paulo",
        "faixa_preco": 2,
        "link": "https://www.google.com/maps/place/Grindhouse+Braserito",
        "imagem_capa": None,
        "fotos": [
            {"url": "https://cdn.example.com/grindhouse.jpg", "capa": True, "ordem": 0}
        ],
        "place_id": "google-grindhouse",
        "extra": {
            "formatted_address": "Rua Teste, 123 - Sao Paulo",
            "rating": 4.7,
            "user_rating_count": 420,
            "phone_number": "+55 11 99999-0000",
            "website_uri": "https://grindhouse.example.com",
            "latitude": -23.56,
            "longitude": -46.68,
            "types": ["restaurant"],
        },
    }

    enriched = JobRunner._build_internal_enriched_item(
        restaurant=restaurant,
        internal_lugar=internal_lugar,
        internal_score=0.94,
    )

    assert enriched.status_matching == StatusMatching.ENCONTRADO_INTERNO
    assert enriched.lugar_id == "lugar-grindhouse"
    assert enriched.place_id == "google-grindhouse"
    assert enriched.google_maps_uri == "https://www.google.com/maps/place/Grindhouse+Braserito"
    assert enriched.site == "https://grindhouse.example.com"
    assert enriched.foto_url == "https://cdn.example.com/grindhouse.jpg"
    assert enriched.rating == 4.7
    assert enriched.total_avaliacoes == 420


def test_internal_match_merge_hydrates_missing_maps_link_without_losing_google_photo() -> None:
    restaurant = ExtractedRestaurant(
        ordem=0,
        nome_original="Grindhouse Braserito",
        nome_normalizado="grindhouse braserito",
    )
    google_enriched = EnrichedItem(
        extracted=restaurant,
        place_id="google-grindhouse",
        foto_url="https://lh3.googleusercontent.com/photo.jpg",
        status_matching=StatusMatching.ENCONTRADO_GOOGLE,
        score_matching=0.91,
        confianca_enriquecimento=0.91,
    )
    internal_lugar = {
        "id": "lugar-grindhouse",
        "nome": "Grindhouse Braserito",
        "link": "https://maps.app.goo.gl/grindhouse",
        "imagem_capa": "https://cdn.example.com/old.jpg",
        "place_id": "google-grindhouse",
        "extra": {},
    }

    merged = JobRunner._merge_internal_match(
        enriched=google_enriched,
        internal_lugar=internal_lugar,
        internal_score=0.96,
        status=StatusMatching.ENCONTRADO_INTERNO,
    )

    assert merged.status_matching == StatusMatching.ENCONTRADO_INTERNO
    assert merged.lugar_id == "lugar-grindhouse"
    assert merged.google_maps_uri == "https://maps.app.goo.gl/grindhouse"
    assert merged.foto_url == "https://lh3.googleusercontent.com/photo.jpg"
    assert merged.score_matching == 0.96


def test_internal_match_with_missing_photo_or_maps_link_needs_google_hydration() -> None:
    restaurant = ExtractedRestaurant(
        ordem=0,
        nome_original="Grindhouse Braserito",
        nome_normalizado="grindhouse braserito",
    )
    item = EnrichedItem(
        extracted=restaurant,
        status_matching=StatusMatching.ENCONTRADO_INTERNO,
        foto_url=None,
        google_maps_uri="https://maps.app.goo.gl/grindhouse",
    )

    assert JobRunner._needs_google_hydration(item) is True


class FakeSupabaseInsertWithoutRepresentation:
    def __init__(self) -> None:
        self.items = []
        self.insert_calls = 0

    async def insert_guia_itens(self, *, items):  # type: ignore[no-untyped-def]
        self.insert_calls += 1
        self.items = items
        return []

    async def list_guia_itens(self, *, guia_id):  # type: ignore[no-untyped-def]
        return [
            {"id": "item-0", "guia_id": guia_id, "ordem": 0},
            {"id": "item-1", "guia_id": guia_id, "ordem": 1},
        ]


@pytest.mark.anyio
async def test_initial_item_insert_recovers_ids_when_supabase_returns_no_rows() -> None:
    fake_supabase = FakeSupabaseInsertWithoutRepresentation()
    runner = JobRunner(
        settings=Settings(),
        supabase_client=fake_supabase,  # type: ignore[arg-type]
        openai_client=object(),  # type: ignore[arg-type]
        google_places_client=object(),  # type: ignore[arg-type]
    )

    item_ids = await runner._inserir_itens_iniciais(
        guia_id="guia-123",
        candidatos=[
            ExtractedRestaurant(
                ordem=0,
                nome_original="Primeiro",
                nome_normalizado="primeiro",
            ),
            ExtractedRestaurant(
                ordem=1,
                nome_original="Segundo",
                nome_normalizado="segundo",
            ),
        ],
    )

    assert item_ids == {0: "item-0", 1: "item-1"}


class FakeSupabaseNoExistingItems:
    def __init__(self) -> None:
        self.insert_calls = 0

    async def list_guia_itens(self, *, guia_id):  # type: ignore[no-untyped-def]
        return []

    async def insert_guia_itens(self, *, items):  # type: ignore[no-untyped-def]
        self.insert_calls += 1
        return [{"id": f"new-{index}", **item} for index, item in enumerate(items)]


@pytest.mark.anyio
async def test_final_persistence_does_not_bulk_insert_when_initial_insert_was_attempted() -> None:
    fake_supabase = FakeSupabaseNoExistingItems()
    runner = JobRunner(
        settings=Settings(),
        supabase_client=fake_supabase,  # type: ignore[arg-type]
        openai_client=object(),  # type: ignore[arg-type]
        google_places_client=object(),  # type: ignore[arg-type]
    )
    alertas: list[str] = []

    await runner._persistir_itens_finais(
        job_id="job-123",
        guia_id="guia-123",
        item_ids={},
        items_finais=[
            EnrichedItem(
                extracted=ExtractedRestaurant(
                    ordem=0,
                    nome_original="Primeiro",
                    nome_normalizado="primeiro",
                ),
                foto_url="https://example.com/foto.jpg",
            )
        ],
        initial_items_insert_attempted=True,
        alertas=alertas,
    )

    assert fake_supabase.insert_calls == 0
    assert "itens_iniciais_sem_ids_para_patch" in alertas


@pytest.mark.anyio
async def test_final_persistence_bulk_inserts_when_no_initial_insert_happened() -> None:
    fake_supabase = FakeSupabaseNoExistingItems()
    runner = JobRunner(
        settings=Settings(),
        supabase_client=fake_supabase,  # type: ignore[arg-type]
        openai_client=object(),  # type: ignore[arg-type]
        google_places_client=object(),  # type: ignore[arg-type]
    )
    alertas: list[str] = []

    await runner._persistir_itens_finais(
        job_id="job-123",
        guia_id="guia-123",
        item_ids={},
        items_finais=[
            EnrichedItem(
                extracted=ExtractedRestaurant(
                    ordem=0,
                    nome_original="Primeiro",
                    nome_normalizado="primeiro",
                ),
                foto_url="https://example.com/foto.jpg",
            )
        ],
        initial_items_insert_attempted=False,
        alertas=alertas,
    )

    assert fake_supabase.insert_calls == 1
    assert alertas == []

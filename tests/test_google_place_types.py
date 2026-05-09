from app.modules.google_places.place_types import (
    friendly_place_type,
    normalize_category_label,
)


def test_friendly_place_type_prefers_google_display_name() -> None:
    assert (
        friendly_place_type("italian_restaurant", "Restaurante italiano")
        == "Restaurante italiano"
    )


def test_friendly_place_type_maps_common_raw_google_types() -> None:
    assert friendly_place_type("italian_restaurant") == "Italiano"
    assert friendly_place_type("cocktail_bar") == "Bar de drinks"
    assert friendly_place_type("restaurant") == "Restaurante"


def test_normalize_category_label_only_rewrites_raw_google_types() -> None:
    assert normalize_category_label("middle_eastern_restaurant") == "Oriente Medio"
    assert normalize_category_label("restaurant") == "Restaurante"
    assert normalize_category_label("Arabe") == "Arabe"

from __future__ import annotations

from typing import Any


_RAW_TYPE_LABELS = {
    "restaurant": "Restaurante",
    "cafe": "Cafe",
    "bar": "Bar",
    "bakery": "Padaria",
    "meal_takeaway": "Para viagem",
    "meal_delivery": "Delivery",
    "food": "Comida",
    "coffee_shop": "Cafeteria",
    "tea_house": "Casa de cha",
    "ice_cream_shop": "Sorveteria",
    "dessert_shop": "Doceria",
    "sandwich_shop": "Sanduicheria",
    "pizza_restaurant": "Pizzaria",
    "hamburger_restaurant": "Hamburgueria",
    "seafood_restaurant": "Frutos do mar",
    "steak_house": "Churrascaria",
    "barbecue_restaurant": "Churrasco",
    "breakfast_restaurant": "Cafe da manha",
    "brunch_restaurant": "Brunch",
    "buffet_restaurant": "Buffet",
    "fast_food_restaurant": "Fast food",
    "fine_dining_restaurant": "Alta gastronomia",
    "vegetarian_restaurant": "Vegetariano",
    "vegan_restaurant": "Vegano",
    "cocktail_bar": "Bar de drinks",
    "wine_bar": "Wine bar",
    "pub": "Pub",
    "sports_bar": "Sports bar",
    "juice_shop": "Sucos",
}

_CUISINE_LABELS = {
    "american": "Americano",
    "asian": "Asiatico",
    "brazilian": "Brasileiro",
    "chinese": "Chines",
    "french": "Frances",
    "greek": "Grego",
    "indian": "Indiano",
    "indonesian": "Indonesio",
    "italian": "Italiano",
    "japanese": "Japones",
    "korean": "Coreano",
    "lebanese": "Libanes",
    "mediterranean": "Mediterraneo",
    "mexican": "Mexicano",
    "middle_eastern": "Oriente Medio",
    "spanish": "Espanhol",
    "thai": "Tailandes",
    "turkish": "Turco",
    "vietnamese": "Vietnamita",
}

_GENERIC_RAW_TYPES = {
    "establishment",
    "point_of_interest",
    "store",
}


def friendly_place_type(
    primary_type: str | None,
    primary_type_display_name: str | None = None,
) -> str | None:
    display_name = _clean(primary_type_display_name)
    if display_name:
        return display_name

    raw_type = _clean(primary_type)
    if not raw_type or raw_type in _GENERIC_RAW_TYPES:
        return None

    mapped = _RAW_TYPE_LABELS.get(raw_type)
    if mapped:
        return mapped

    if raw_type.endswith("_restaurant"):
        cuisine = raw_type[: -len("_restaurant")]
        return _CUISINE_LABELS.get(cuisine) or _title_from_raw(cuisine)

    if raw_type.endswith("_bar"):
        qualifier = raw_type[: -len("_bar")]
        qualifier_label = _title_from_raw(qualifier)
        return f"Bar {qualifier_label}" if qualifier_label else "Bar"

    if "_" in raw_type:
        return _title_from_raw(raw_type)

    return None


def normalize_category_label(value: Any) -> str | None:
    label = _clean(value)
    if not label:
        return None

    if label in _RAW_TYPE_LABELS or label in _GENERIC_RAW_TYPES or "_" in label:
        return friendly_place_type(label)

    return label


def _clean(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.strip().split())
    return normalized or None


def _title_from_raw(value: str) -> str | None:
    cleaned = value.replace("_", " ").strip()
    if not cleaned:
        return None
    return cleaned.capitalize()

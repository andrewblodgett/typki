import re
from collections.abc import Mapping
from dataclasses import dataclass

DECK_SEPARATOR = "::"
DEFAULT_PAGE_WIDTH = "80mm"
DEFAULT_SCALE = 1.5
DEFAULT_TEMPLATE = "blank"
DEFAULT_FIT_WIDTH = True
LENGTH_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(mm|cm|in|pt)\s*$")
MILLIMETRES_PER_UNIT = {"mm": 1.0, "cm": 10.0, "in": 25.4, "pt": 25.4 / 72}
SLUG_SEPARATOR = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class DeckConfig:
    anki_deck: str
    page_width: str = DEFAULT_PAGE_WIDTH
    scale: float = DEFAULT_SCALE
    default_template: str = DEFAULT_TEMPLATE
    default_tags: tuple[str, ...] = ()
    fit_width: bool = DEFAULT_FIT_WIDTH
    folder: str | None = None


def ancestor_deck_names(deck_name: str) -> list[str]:
    parts = deck_name.split(DECK_SEPARATOR)
    return [DECK_SEPARATOR.join(parts[:length]) for length in range(len(parts), 0, -1)]


def is_same_or_descendant(deck_name: str, ancestor: str) -> bool:
    return deck_name == ancestor or deck_name.startswith(ancestor + DECK_SEPARATOR)


def resolve_deck_config(deck_name: str, configs_by_deck: Mapping[str, DeckConfig]) -> DeckConfig:
    for candidate in ancestor_deck_names(deck_name):
        if candidate in configs_by_deck:
            return configs_by_deck[candidate]
    return DeckConfig(anki_deck=deck_name)


def length_to_mm(length: str) -> float | None:
    match = LENGTH_PATTERN.match(length)
    if match is None:
        return None
    return float(match.group(1)) * MILLIMETRES_PER_UNIT[match.group(2)]


def format_mm(millimetres: float) -> str:
    return f"{millimetres:g}mm"


def deck_slug(deck_name: str) -> str:
    return SLUG_SEPARATOR.sub("-", deck_name.lower()).strip("-") or "deck"

from collections.abc import Mapping
from dataclasses import dataclass

DECK_SEPARATOR = "::"
DEFAULT_PAGE_WIDTH = "80mm"
DEFAULT_SCALE = 1.5
DEFAULT_TEMPLATE = "blank"


@dataclass(frozen=True)
class DeckConfig:
    anki_deck: str
    page_width: str = DEFAULT_PAGE_WIDTH
    scale: float = DEFAULT_SCALE
    default_template: str = DEFAULT_TEMPLATE
    default_tags: tuple[str, ...] = ()
    folder: str | None = None


def ancestor_deck_names(deck_name: str) -> list[str]:
    parts = deck_name.split(DECK_SEPARATOR)
    return [DECK_SEPARATOR.join(parts[:length]) for length in range(len(parts), 0, -1)]


def resolve_deck_config(deck_name: str, configs_by_deck: Mapping[str, DeckConfig]) -> DeckConfig:
    for candidate in ancestor_deck_names(deck_name):
        if candidate in configs_by_deck:
            return configs_by_deck[candidate]
    return DeckConfig(anki_deck=deck_name)

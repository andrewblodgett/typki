from dataclasses import dataclass

from typki.anki import note_type
from typki.anki.search import deck_exactly_terms, quoted_term
from typki.domain.deck import is_same_or_descendant


@dataclass(frozen=True)
class DeckStaleness:
    deck_name: str
    stale_note_ids: tuple[int, ...]
    total: int


@dataclass(frozen=True)
class StalenessReport:
    root_deck: str | None
    decks: tuple[DeckStaleness, ...]

    @property
    def stale_note_ids(self) -> tuple[int, ...]:
        return tuple(note_id for deck in self.decks for note_id in deck.stale_note_ids)

    @property
    def stale_count(self) -> int:
        return sum(len(deck.stale_note_ids) for deck in self.decks)

    @property
    def total(self) -> int:
        return sum(deck.total for deck in self.decks)


def decks_in_scope(all_deck_names: list[str], root_deck: str | None) -> list[str]:
    if root_deck is None:
        return sorted(all_deck_names)
    return sorted(name for name in all_deck_names if is_same_or_descendant(name, root_deck))


def deck_notes_query(type_query: str, deck_name: str) -> str:
    return f"{type_query} {deck_exactly_terms(deck_name)}"


def fresh_notes_query(type_query: str, deck_name: str, preamble_hash: str, renderer_version: str) -> str:
    return (
        f"{deck_notes_query(type_query, deck_name)} "
        f"{quoted_term(note_type.PREAMBLE_HASH, preamble_hash)} "
        f"{quoted_term(note_type.RENDERER_VERSION, renderer_version)}"
    )


def chunked(items: tuple[int, ...] | list[int], size: int) -> list[list[int]]:
    return [list(items[start : start + size]) for start in range(0, len(items), size)]

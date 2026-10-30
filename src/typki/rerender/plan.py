from dataclasses import dataclass

from typki.anki import note_type
from typki.anki.search import quoted_term


@dataclass(frozen=True)
class StalenessReport:
    stale_note_ids: tuple[int, ...]
    total: int

    @property
    def stale_count(self) -> int:
        return len(self.stale_note_ids)


def fresh_notes_query(type_query: str, preamble_hash: str, renderer_version: str) -> str:
    return (
        f"{type_query} "
        f"{quoted_term(note_type.PREAMBLE_HASH, preamble_hash)} "
        f"{quoted_term(note_type.RENDERER_VERSION, renderer_version)}"
    )


def chunked(items: tuple[int, ...] | list[int], size: int) -> list[list[int]]:
    return [list(items[start : start + size]) for start in range(0, len(items), size)]

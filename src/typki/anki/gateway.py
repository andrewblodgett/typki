from dataclasses import dataclass
from typing import Protocol


class AnkiError(Exception):
    pass


class AnkiUnavailableError(AnkiError):
    pass


class DuplicateNoteError(AnkiError):
    pass


@dataclass(frozen=True)
class NewNote:
    deck_name: str
    model_name: str
    fields: dict[str, str]
    tags: tuple[str, ...]


@dataclass(frozen=True)
class NoteRecord:
    note_id: int
    model_name: str
    tags: tuple[str, ...]
    fields: dict[str, str]
    card_ids: tuple[int, ...]
    modified: int
    deck_name: str


class AnkiGateway(Protocol):
    def version(self) -> int: ...

    def deck_names(self) -> list[str]: ...

    def create_deck(self, deck_name: str) -> None: ...

    def model_names(self) -> list[str]: ...

    def model_field_names(self, model_name: str) -> list[str]: ...

    def model_templates(self, model_name: str) -> dict[str, dict[str, str]]: ...

    def model_styling(self, model_name: str) -> str: ...

    def create_model(
        self,
        model_name: str,
        field_names: list[str],
        css: str,
        templates: list[dict[str, str]],
    ) -> None: ...

    def add_model_field(self, model_name: str, field_name: str) -> None: ...

    def update_model_templates(self, model_name: str, templates: dict[str, dict[str, str]]) -> None: ...

    def update_model_styling(self, model_name: str, css: str) -> None: ...

    def get_tags(self) -> list[str]: ...

    def add_note(self, note: NewNote) -> int: ...

    def update_note_fields(self, note_id: int, fields: dict[str, str]) -> None: ...

    def update_note_tags(self, note_id: int, tags: tuple[str, ...]) -> None: ...

    def change_deck(self, card_ids: tuple[int, ...], deck_name: str) -> None: ...

    def find_notes(self, query: str) -> list[int]: ...

    def notes_info(self, note_ids: list[int]) -> list[NoteRecord]: ...

    def delete_notes(self, note_ids: list[int]) -> None: ...

import json
import time
import urllib.error
import urllib.request
from typing import Any

from typki.anki.gateway import (
    AnkiError,
    AnkiUnavailableError,
    DuplicateNoteError,
    NewNote,
    NoteRecord,
)

DEFAULT_URL = "http://127.0.0.1:8765"
API_VERSION = 6
RETRY_DELAYS_SECONDS = (0.15, 0.4)
DUPLICATE_MARKER = "duplicate"
CARDS_INFO_CHUNK = 500


class AnkiConnectGateway:
    def __init__(self, url: str = DEFAULT_URL, timeout_seconds: float = 10.0) -> None:
        self.url = url
        self.timeout_seconds = timeout_seconds

    def invoke(self, action: str, **params: Any) -> Any:
        payload = json.dumps({"action": action, "version": API_VERSION, "params": params}).encode()
        request = urllib.request.Request(self.url, payload, headers={"Content-Type": "application/json"})
        body = self._send_with_retries(request)
        reply = json.loads(body)
        error = reply.get("error")
        if error is not None:
            if DUPLICATE_MARKER in str(error):
                raise DuplicateNoteError(str(error))
            raise AnkiError(f"{action}: {error}")
        return reply.get("result")

    def _send_with_retries(self, request: urllib.request.Request) -> bytes:
        last_error: Exception | None = None
        for delay in (0.0, *RETRY_DELAYS_SECONDS):
            if delay:
                time.sleep(delay)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    body: bytes = response.read()
                    return body
            except (urllib.error.URLError, ConnectionError, TimeoutError) as error:
                last_error = error
        raise AnkiUnavailableError(f"AnkiConnect is not reachable at {self.url}: {last_error}")

    def version(self) -> int:
        return int(self.invoke("version"))

    def deck_names(self) -> list[str]:
        return list(self.invoke("deckNames"))

    def create_deck(self, deck_name: str) -> None:
        self.invoke("createDeck", deck=deck_name)

    def model_names(self) -> list[str]:
        return list(self.invoke("modelNames"))

    def model_field_names(self, model_name: str) -> list[str]:
        return list(self.invoke("modelFieldNames", modelName=model_name))

    def model_templates(self, model_name: str) -> dict[str, dict[str, str]]:
        return dict(self.invoke("modelTemplates", modelName=model_name))

    def model_styling(self, model_name: str) -> str:
        return str(self.invoke("modelStyling", modelName=model_name).get("css", ""))

    def create_model(
        self,
        model_name: str,
        field_names: list[str],
        css: str,
        templates: list[dict[str, str]],
    ) -> None:
        self.invoke(
            "createModel",
            modelName=model_name,
            inOrderFields=field_names,
            css=css,
            isCloze=False,
            cardTemplates=templates,
        )

    def add_model_field(self, model_name: str, field_name: str) -> None:
        self.invoke("modelFieldAdd", modelName=model_name, fieldName=field_name)

    def update_model_templates(self, model_name: str, templates: dict[str, dict[str, str]]) -> None:
        self.invoke("updateModelTemplates", model={"name": model_name, "templates": templates})

    def update_model_styling(self, model_name: str, css: str) -> None:
        self.invoke("updateModelStyling", model={"name": model_name, "css": css})

    def get_tags(self) -> list[str]:
        return list(self.invoke("getTags"))

    def add_note(self, note: NewNote) -> int:
        return int(
            self.invoke(
                "addNote",
                note={
                    "deckName": note.deck_name,
                    "modelName": note.model_name,
                    "fields": note.fields,
                    "tags": list(note.tags),
                },
            )
        )

    def update_note_fields(self, note_id: int, fields: dict[str, str]) -> None:
        self.invoke("updateNoteFields", note={"id": note_id, "fields": fields})

    def update_note_tags(self, note_id: int, tags: tuple[str, ...]) -> None:
        self.invoke("updateNoteTags", note=note_id, tags=list(tags))

    def change_deck(self, card_ids: tuple[int, ...], deck_name: str) -> None:
        self.invoke("changeDeck", cards=list(card_ids), deck=deck_name)

    def find_notes(self, query: str) -> list[int]:
        return [int(note_id) for note_id in self.invoke("findNotes", query=query)]

    def notes_info(self, note_ids: list[int]) -> list[NoteRecord]:
        if not note_ids:
            return []
        raw_notes = [note for note in self.invoke("notesInfo", notes=note_ids) if note]
        first_card_ids = [note["cards"][0] for note in raw_notes if note.get("cards")]
        deck_by_card = self._deck_names_by_card(first_card_ids)
        return [to_note_record(note, deck_by_card) for note in raw_notes]

    def _deck_names_by_card(self, card_ids: list[int]) -> dict[int, str]:
        deck_by_card: dict[int, str] = {}
        for start in range(0, len(card_ids), CARDS_INFO_CHUNK):
            chunk = card_ids[start : start + CARDS_INFO_CHUNK]
            for card in self.invoke("cardsInfo", cards=chunk):
                deck_by_card[int(card["cardId"])] = str(card["deckName"])
        return deck_by_card

    def delete_notes(self, note_ids: list[int]) -> None:
        self.invoke("deleteNotes", notes=note_ids)


def to_note_record(raw_note: dict[str, Any], deck_by_card: dict[int, str]) -> NoteRecord:
    card_ids = tuple(int(card_id) for card_id in raw_note.get("cards", []))
    return NoteRecord(
        note_id=int(raw_note["noteId"]),
        model_name=str(raw_note["modelName"]),
        tags=tuple(raw_note.get("tags", [])),
        fields={name: str(field["value"]) for name, field in raw_note["fields"].items()},
        card_ids=card_ids,
        modified=int(raw_note.get("mod", 0)),
        deck_name=deck_by_card.get(card_ids[0], "") if card_ids else "",
    )

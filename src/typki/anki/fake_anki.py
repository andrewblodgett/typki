import itertools
import json
import re
import shlex
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

HTML_TAG = re.compile(r"<[^>]+>")
DEFAULT_DECK = "Default"


def strip_html(value: str) -> str:
    return HTML_TAG.sub("", value).strip()


@dataclass
class FakeModel:
    name: str
    fields: list[str]
    css: str
    templates: dict[str, dict[str, str]]


@dataclass
class FakeNote:
    note_id: int
    model_name: str
    fields: dict[str, str]
    tags: list[str]
    card_id: int
    deck_name: str
    modified: int
    review_count: int = 0


@dataclass
class FakeAnki:
    decks: set[str] = field(default_factory=lambda: {DEFAULT_DECK})
    models: dict[str, FakeModel] = field(default_factory=dict)
    notes: dict[int, FakeNote] = field(default_factory=dict)
    ids: Iterator[int] = field(default_factory=lambda: itertools.count(1_700_000_000_000))
    lock: threading.RLock = field(default_factory=threading.RLock)

    def handle(self, action: str, params: dict[str, Any]) -> Any:
        handler = getattr(self, f"action_{action}", None)
        if handler is None:
            raise ValueError(f"unsupported action {action}")
        with self.lock:
            return handler(**params)

    def action_version(self) -> int:
        return 6

    def action_deckNames(self) -> list[str]:
        return sorted(self.decks)

    def action_createDeck(self, deck: str) -> int:
        parts = deck.split("::")
        for length in range(1, len(parts) + 1):
            self.decks.add("::".join(parts[:length]))
        return abs(hash(deck))

    def action_modelNames(self) -> list[str]:
        return sorted(self.models)

    def action_createModel(
        self,
        modelName: str,
        inOrderFields: list[str],
        css: str,
        cardTemplates: list[dict[str, str]],
        isCloze: bool = False,
    ) -> dict[str, Any]:
        if modelName in self.models:
            raise ValueError("Model name already exists")
        templates = {
            template.get("Name", f"Card {index + 1}"): {
                "Front": template["Front"],
                "Back": template["Back"],
            }
            for index, template in enumerate(cardTemplates)
        }
        self.models[modelName] = FakeModel(modelName, list(inOrderFields), css, templates)
        return {"name": modelName}

    def action_modelFieldNames(self, modelName: str) -> list[str]:
        return list(self.require_model(modelName).fields)

    def action_modelTemplates(self, modelName: str) -> dict[str, dict[str, str]]:
        return dict(self.require_model(modelName).templates)

    def action_modelStyling(self, modelName: str) -> dict[str, str]:
        return {"css": self.require_model(modelName).css}

    def action_modelFieldAdd(self, modelName: str, fieldName: str, index: int | None = None) -> None:
        model = self.require_model(modelName)
        model.fields.append(fieldName)
        for note in self.notes.values():
            if note.model_name == modelName:
                note.fields.setdefault(fieldName, "")

    def action_updateModelTemplates(self, model: dict[str, Any]) -> None:
        self.require_model(model["name"]).templates.update(model["templates"])

    def action_updateModelStyling(self, model: dict[str, Any]) -> None:
        self.require_model(model["name"]).css = model["css"]

    def action_getTags(self) -> list[str]:
        return sorted({tag for note in self.notes.values() for tag in note.tags})

    def action_addNote(self, note: dict[str, Any]) -> int:
        model = self.require_model(note["modelName"])
        if note["deckName"] not in self.decks:
            raise ValueError("deck was not found")
        fields = {name: str(note["fields"].get(name, "")) for name in model.fields}
        first_field = strip_html(fields[model.fields[0]])
        if not first_field:
            raise ValueError("cannot create note because it is empty")
        for existing in self.notes.values():
            if (
                existing.model_name == model.name
                and strip_html(existing.fields[model.fields[0]]) == first_field
            ):
                raise ValueError("cannot create note because it is a duplicate")
        note_id = next(self.ids)
        self.notes[note_id] = FakeNote(
            note_id=note_id,
            model_name=model.name,
            fields=fields,
            tags=list(note.get("tags", [])),
            card_id=next(self.ids),
            deck_name=note["deckName"],
            modified=int(time.time()),
        )
        return note_id

    def action_updateNoteFields(self, note: dict[str, Any]) -> None:
        stored = self.require_note(note["id"])
        for name, value in note["fields"].items():
            if name in stored.fields:
                stored.fields[name] = value
        stored.modified = int(time.time())

    def action_updateNoteTags(self, note: int, tags: list[str]) -> None:
        self.require_note(note).tags = list(tags)

    def action_changeDeck(self, cards: list[int], deck: str) -> None:
        self.action_createDeck(deck)
        for stored in self.notes.values():
            if stored.card_id in cards:
                stored.deck_name = deck

    def action_deleteNotes(self, notes: list[int]) -> None:
        for note_id in notes:
            self.notes.pop(note_id, None)

    def action_findNotes(self, query: str) -> list[int]:
        terms = shlex.split(query)
        return sorted(
            note.note_id
            for note in self.notes.values()
            if all(self.matches_term(note, term) for term in terms)
        )

    def action_notesInfo(self, notes: list[int]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for note_id in notes:
            stored = self.notes.get(note_id)
            if stored is None:
                result.append({})
                continue
            model = self.require_model(stored.model_name)
            result.append(
                {
                    "noteId": stored.note_id,
                    "modelName": stored.model_name,
                    "tags": list(stored.tags),
                    "fields": {
                        name: {"value": stored.fields.get(name, ""), "order": index}
                        for index, name in enumerate(model.fields)
                    },
                    "cards": [stored.card_id],
                    "mod": stored.modified,
                }
            )
        return result

    def action_cardsInfo(self, cards: list[int]) -> list[dict[str, Any]]:
        by_card = {note.card_id: note for note in self.notes.values()}
        return [
            {"cardId": card_id, "note": by_card[card_id].note_id, "deckName": by_card[card_id].deck_name}
            for card_id in cards
            if card_id in by_card
        ]

    def action_multi(self, actions: list[dict[str, Any]]) -> list[Any]:
        results: list[Any] = []
        for entry in actions:
            try:
                result = self.handle(entry["action"], entry.get("params", {}))
            except ValueError as error:
                results.append({"result": None, "error": str(error)})
                continue
            results.append({"result": result, "error": None} if "version" in entry else result)
        return results

    def matches_term(self, note: FakeNote, term: str) -> bool:
        if term.startswith("-"):
            return not self.matches_term(note, term[1:])
        key, separator, value = term.partition(":")
        if not separator:
            needle = term.lower()
            return any(needle in strip_html(text).lower() for text in note.fields.values())
        lowered_key = key.lower()
        if lowered_key == "note":
            return note.model_name == value
        if lowered_key == "deck":
            return any(
                search_pattern_matches(value, candidate) for candidate in deck_and_ancestors(note.deck_name)
            )
        if lowered_key == "tag":
            return value in note.tags
        if lowered_key == "nid":
            return str(note.note_id) in value.split(",")
        for name, text in note.fields.items():
            if name.lower() == lowered_key:
                return search_pattern_matches(value, text)
        return False

    def require_model(self, name: str) -> FakeModel:
        if name not in self.models:
            raise ValueError(f"model was not found: {name}")
        return self.models[name]

    def require_note(self, note_id: int) -> FakeNote:
        if note_id not in self.notes:
            raise ValueError(f"note was not found: {note_id}")
        return self.notes[note_id]


def deck_and_ancestors(deck_name: str) -> list[str]:
    parts = deck_name.split("::")
    return ["::".join(parts[:length]) for length in range(len(parts), 0, -1)]


def search_pattern_matches(pattern: str, text: str) -> bool:
    regex = ""
    index = 0
    while index < len(pattern):
        character = pattern[index]
        if character == "\\" and index + 1 < len(pattern):
            regex += re.escape(pattern[index + 1])
            index += 2
            continue
        if character == "*":
            regex += ".*"
        elif character == "_":
            regex += "."
        else:
            regex += re.escape(character)
        index += 1
    return re.fullmatch(regex, text, flags=re.IGNORECASE | re.DOTALL) is not None


def make_handler(fake: FakeAnki) -> type[BaseHTTPRequestHandler]:
    class FakeAnkiConnectHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(length))
            try:
                reply = {"result": fake.handle(request["action"], request.get("params", {})), "error": None}
            except ValueError as error:
                reply = {"result": None, "error": str(error)}
            body = json.dumps(reply).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return FakeAnkiConnectHandler


@contextmanager
def running_fake_ankiconnect(fake: FakeAnki | None = None) -> Iterator[tuple[str, FakeAnki]]:
    state = fake or FakeAnki()
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", state
    finally:
        server.shutdown()
        server.server_close()

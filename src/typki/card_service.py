from dataclasses import dataclass

from typki.anki import note_type
from typki.anki.gateway import AnkiError, AnkiGateway, NewNote, NoteRecord
from typki.anki.note_type import NOTE_TYPE_NAME, NoteTypeHealth, diagnose_note_type
from typki.anki.search import quoted_term
from typki.domain.card import CardDraft, StoredCard
from typki.domain.preamble import Preamble
from typki.domain.staleness import is_stale
from typki.library.store import Library
from typki.render.compiler import Renderer, SideRender

DEFAULT_SEARCH_LIMIT = 40
UPDATE_NOT_APPLIED_MESSAGE = (
    "Anki did not apply the update. If this note is open in Anki's Browse window "
    "or editor, close it there and save again."
)


class RenderFailedError(Exception):
    def __init__(self, card_render: CardRender) -> None:
        super().__init__("The card has compile errors, so nothing was saved.")
        self.card_render = card_render


class NotTypkiNoteError(AnkiError):
    pass


@dataclass(frozen=True)
class CardRender:
    front: SideRender
    back: SideRender
    preamble_hash: str
    renderer_version: str

    @property
    def ok(self) -> bool:
        return self.front.ok and self.back.ok


@dataclass(frozen=True)
class SaveResult:
    note_id: int
    created: bool


@dataclass(frozen=True)
class OpenedCard:
    card: StoredCard
    stale: bool
    drifted: bool


@dataclass(frozen=True)
class CardSummary:
    card: StoredCard
    stale: bool


@dataclass(frozen=True)
class SearchResult:
    cards: tuple[CardSummary, ...]
    total: int


def note_type_query() -> str:
    return quoted_term("note", NOTE_TYPE_NAME)


def to_stored_card(record: NoteRecord) -> StoredCard:
    fields = record.fields
    return StoredCard(
        note_id=record.note_id,
        deck_name=record.deck_name,
        tags=record.tags,
        front_source=fields.get(note_type.FRONT_SOURCE, ""),
        back_source=fields.get(note_type.BACK_SOURCE, ""),
        source_id=fields.get(note_type.SOURCE_ID, ""),
        preamble_hash=fields.get(note_type.PREAMBLE_HASH, ""),
        renderer_version=fields.get(note_type.RENDERER_VERSION, ""),
        front_svg=fields.get(note_type.FRONT, ""),
        back_svg=fields.get(note_type.BACK, ""),
        card_ids=record.card_ids,
        modified=record.modified,
    )


class CardService:
    def __init__(self, gateway: AnkiGateway, library: Library, renderer: Renderer) -> None:
        self.gateway = gateway
        self.library = library
        self.renderer = renderer

    def check_note_type(self) -> NoteTypeHealth:
        model_names = self.gateway.model_names()
        if NOTE_TYPE_NAME not in model_names:
            return NoteTypeHealth(exists=False)
        return diagnose_note_type(
            model_names,
            self.gateway.model_field_names(NOTE_TYPE_NAME),
            self.gateway.model_templates(NOTE_TYPE_NAME),
            self.gateway.model_styling(NOTE_TYPE_NAME),
        )

    def create_note_type(self) -> None:
        self.gateway.create_model(
            NOTE_TYPE_NAME,
            list(note_type.FIELD_NAMES),
            note_type.CARD_CSS,
            [
                {
                    "Name": note_type.CARD_TEMPLATE_NAME,
                    "Front": note_type.FRONT_TEMPLATE,
                    "Back": note_type.BACK_TEMPLATE,
                }
            ],
        )

    def repair_note_type(self, health: NoteTypeHealth) -> None:
        if not health.exists:
            self.create_note_type()
            return
        for field_name in health.missing_fields:
            self.gateway.add_model_field(NOTE_TYPE_NAME, field_name)
        if health.templates_differ:
            self.gateway.update_model_templates(
                NOTE_TYPE_NAME,
                {
                    note_type.CARD_TEMPLATE_NAME: {
                        "Front": note_type.FRONT_TEMPLATE,
                        "Back": note_type.BACK_TEMPLATE,
                    }
                },
            )
        if health.styling_differs:
            self.gateway.update_model_styling(NOTE_TYPE_NAME, note_type.CARD_CSS)

    def render(self, front_source: str, back_source: str) -> CardRender:
        return self.render_with(self.library.preamble(), front_source, back_source)

    def render_with(self, preamble: Preamble, front_source: str, back_source: str) -> CardRender:
        return CardRender(
            front=self.renderer.render_side(front_source, preamble),
            back=self.renderer.render_side(back_source, preamble),
            preamble_hash=preamble.hash,
            renderer_version=self.renderer.renderer_version,
        )

    def is_stale(self, card: StoredCard, preamble: Preamble) -> bool:
        return is_stale(
            card.preamble_hash, card.renderer_version, preamble.hash, self.renderer.renderer_version
        )

    def save(self, draft: CardDraft) -> SaveResult:
        card_render = self.render(draft.front, draft.back)
        if not card_render.ok:
            raise RenderFailedError(card_render)
        fields = self.rendered_fields(draft, card_render)
        existing_note_id = draft.note_id or self.find_by_source_id(draft.source_id)
        if existing_note_id is not None:
            self.update_existing(existing_note_id, draft, fields)
            return SaveResult(note_id=existing_note_id, created=False)
        self.gateway.create_deck(draft.deck_name)
        note_id = self.gateway.add_note(
            NewNote(
                deck_name=draft.deck_name,
                model_name=NOTE_TYPE_NAME,
                fields=fields,
                tags=draft.tags,
            )
        )
        return SaveResult(note_id=note_id, created=True)

    def rendered_fields(self, draft: CardDraft, card_render: CardRender) -> dict[str, str]:
        assert card_render.front.svg is not None and card_render.back.svg is not None
        return {
            note_type.FRONT: card_render.front.svg,
            note_type.BACK: card_render.back.svg,
            note_type.FRONT_SOURCE: draft.front,
            note_type.BACK_SOURCE: draft.back,
            note_type.SOURCE_ID: draft.source_id,
            note_type.PREAMBLE_HASH: card_render.preamble_hash,
            note_type.RENDERER_VERSION: card_render.renderer_version,
        }

    def find_by_source_id(self, source_id: str) -> int | None:
        matches = self.gateway.find_notes(
            f"{note_type_query()} {quoted_term(note_type.SOURCE_ID, source_id)}"
        )
        return matches[0] if matches else None

    def update_existing(self, note_id: int, draft: CardDraft, fields: dict[str, str]) -> None:
        record = self.require_typki_record(note_id)
        stored_source_id = record.fields.get(note_type.SOURCE_ID, "")
        if stored_source_id:
            fields = {**fields, note_type.SOURCE_ID: stored_source_id}
        self.gateway.update_note_fields(note_id, fields)
        if set(record.tags) != set(draft.tags):
            self.gateway.update_note_tags(note_id, draft.tags)
        if record.deck_name != draft.deck_name and record.card_ids:
            self.gateway.change_deck(record.card_ids, draft.deck_name)
        updated = self.require_typki_record(note_id)
        if (
            updated.fields.get(note_type.FRONT_SOURCE) != fields[note_type.FRONT_SOURCE]
            or updated.fields.get(note_type.FRONT) != fields[note_type.FRONT]
        ):
            raise AnkiError(UPDATE_NOT_APPLIED_MESSAGE)

    def require_typki_record(self, note_id: int) -> NoteRecord:
        records = self.gateway.notes_info([note_id])
        if not records:
            raise AnkiError(f"Note {note_id} no longer exists in Anki.")
        record = records[0]
        if record.model_name != NOTE_TYPE_NAME:
            raise NotTypkiNoteError(f"Note {note_id} was not created by Typki and is read-only.")
        return record

    def open(self, note_id: int) -> OpenedCard:
        card = to_stored_card(self.require_typki_record(note_id))
        preamble = self.library.preamble()
        if self.is_stale(card, preamble):
            return OpenedCard(card=card, stale=True, drifted=False)
        fresh = self.render_with(preamble, card.front_source, card.back_source)
        drifted = fresh.ok and (fresh.front.svg != card.front_svg or fresh.back.svg != card.back_svg)
        return OpenedCard(card=card, stale=False, drifted=drifted)

    def search(self, query: str, offset: int = 0, limit: int = DEFAULT_SEARCH_LIMIT) -> SearchResult:
        note_ids = sorted(self.gateway.find_notes(f"{note_type_query()} {query}".strip()), reverse=True)
        records = self.gateway.notes_info(note_ids[offset : offset + limit])
        preamble = self.library.preamble()
        summaries = tuple(
            CardSummary(card=card, stale=self.is_stale(card, preamble))
            for card in (to_stored_card(record) for record in records)
        )
        return SearchResult(cards=summaries, total=len(note_ids))

import pytest

from typki.anki import note_type
from typki.anki.ankiconnect import AnkiConnectGateway
from typki.anki.fake_anki import FakeAnki
from typki.anki.gateway import AnkiError, DuplicateNoteError
from typki.card_service import CardService, NotTypkiNoteError, RenderFailedError
from typki.domain.card import CardDraft

DECK = "Real Analysis"


def make_draft(
    front: str = "*Define* compactness.", back: str = "Every open cover has a finite subcover."
) -> CardDraft:
    return CardDraft(
        deck_name=DECK, template_name="definition", tags=("real-analysis",), front=front, back=back
    )


def test_note_type_is_created_healthy(service: CardService) -> None:
    assert service.check_note_type().healthy


def test_note_type_repair(
    service: CardService, fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki]
) -> None:
    _, fake = fake_ankiconnect
    model = fake.models[note_type.NOTE_TYPE_NAME]
    model.fields.remove(note_type.RENDERER_VERSION)
    model.css = "broken"
    health = service.check_note_type()
    assert health.missing_fields == (note_type.RENDERER_VERSION,)
    assert health.styling_differs
    service.repair_note_type(health)
    assert service.check_note_type().healthy


def test_save_new_card_stores_source_and_svg(
    service: CardService, fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki]
) -> None:
    _, fake = fake_ankiconnect
    draft = make_draft()
    result = service.save(draft)
    assert result.created
    stored = fake.notes[result.note_id]
    assert stored.deck_name == DECK
    assert stored.tags == ["real-analysis"]
    assert stored.fields[note_type.FRONT_SOURCE] == draft.front
    assert stored.fields[note_type.SOURCE_ID] == draft.source_id
    assert stored.fields[note_type.FRONT].startswith("<svg")
    assert "compactness" in stored.fields[note_type.FRONT]


def test_retry_with_same_source_id_updates_instead_of_duplicating(
    service: CardService, fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki]
) -> None:
    _, fake = fake_ankiconnect
    draft = make_draft()
    first = service.save(draft)
    second = service.save(draft)
    assert not second.created
    assert second.note_id == first.note_id
    assert len(fake.notes) == 1


def test_compile_error_saves_nothing(
    service: CardService, fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki]
) -> None:
    _, fake = fake_ankiconnect
    with pytest.raises(RenderFailedError) as raised:
        service.save(make_draft(front="$ nope(x) $"))
    assert raised.value.card_render.front.errors
    assert not fake.notes


def test_duplicate_front_is_rejected(service: CardService) -> None:
    service.save(make_draft())
    with pytest.raises(DuplicateNoteError):
        service.save(make_draft())


def test_edit_updates_in_place_and_keeps_history(
    service: CardService, fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki]
) -> None:
    _, fake = fake_ankiconnect
    note_id = service.save(make_draft()).note_id
    fake.notes[note_id].review_count = 7
    opened = service.open(note_id)
    assert not service.is_stale(opened, service.library.preamble())
    edited = CardDraft(
        deck_name="Real Analysis::Topology",
        template_name="definition",
        tags=("real-analysis", "topology"),
        front=opened.front_source,
        back="Every open cover has a *finite* subcover.",
        source_id=opened.source_id,
        note_id=note_id,
    )
    result = service.save(edited)
    assert result.note_id == note_id and not result.created
    stored = fake.notes[note_id]
    assert stored.review_count == 7
    assert stored.fields[note_type.BACK_SOURCE] == edited.back
    assert stored.deck_name == "Real Analysis::Topology"
    assert stored.tags == ["real-analysis", "topology"]
    assert len(fake.notes) == 1


def test_edit_keeps_original_source_id(
    service: CardService, fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki]
) -> None:
    _, fake = fake_ankiconnect
    original = make_draft()
    note_id = service.save(original).note_id
    service.save(CardDraft(DECK, "blank", (), "*Define* compactness.", "changed", note_id=note_id))
    assert fake.notes[note_id].fields[note_type.SOURCE_ID] == original.source_id


def test_header_change_makes_card_stale(service: CardService) -> None:
    note_id = service.save(make_draft()).note_id
    service.library.write_header(service.library.read_header() + "#let changed = 1\n")
    assert service.is_stale(service.open(note_id), service.library.preamble())


def test_delete_removes_note(
    service: CardService, fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki]
) -> None:
    _, fake = fake_ankiconnect
    note_id = service.save(make_draft()).note_id
    service.delete(note_id)
    assert note_id not in fake.notes


def test_open_rejects_foreign_notes(
    service: CardService, fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki]
) -> None:
    gateway, fake = fake_ankiconnect
    gateway.create_model(
        "Basic", ["Front", "Back"], "", [{"Name": "Card 1", "Front": "{{Front}}", "Back": "{{Back}}"}]
    )
    foreign_id = fake.handle(
        "addNote",
        {"note": {"deckName": "Default", "modelName": "Basic", "fields": {"Front": "q", "Back": "a"}}},
    )
    with pytest.raises(NotTypkiNoteError):
        service.open(foreign_id)


def test_update_not_applied_is_detected(
    service: CardService,
    fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway, _ = fake_ankiconnect
    draft = make_draft()
    note_id = service.save(draft).note_id
    monkeypatch.setattr(gateway, "update_note_fields", lambda note_id, fields: None)
    with pytest.raises(AnkiError, match="did not apply"):
        service.save(CardDraft(DECK, "blank", (), "new front", "new back", draft.source_id, note_id))


def test_search_lists_newest_first_with_staleness(service: CardService) -> None:
    first = service.save(make_draft(front="first card")).note_id
    second = service.save(make_draft(front="second card")).note_id
    service.save(CardDraft("Biology", "blank", (), "cell", "unit of life"))
    result = service.search(f'"deck:{DECK}"')
    assert result.total == 2
    assert [summary.card.note_id for summary in result.cards] == [second, first]
    assert not any(summary.stale for summary in result.cards)
    service.library.write_header(service.library.read_header() + "#let changed = 2\n")
    assert all(summary.stale for summary in service.search("").cards)


def test_search_by_text_uses_desc(service: CardService) -> None:
    service.save(make_draft(front="Bolzano Weierstrass"))
    service.save(make_draft(front="Heine Borel"))
    result = service.search("Borel")
    assert [summary.card.front_source for summary in result.cards] == ["Heine Borel"]

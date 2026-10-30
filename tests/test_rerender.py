import threading

from typki.anki import note_type
from typki.anki.ankiconnect import AnkiConnectGateway
from typki.anki.fake_anki import FakeAnki
from typki.anki.search import deck_exactly_terms, escape_search_text
from typki.card_service import CardService
from typki.domain.card import CardDraft
from typki.rerender.runner import Rerenderer, RerenderProgress, group_failures

DECK = "Real Analysis"
MACROS = "decks/real-analysis/macros.typ"


def add_cards(service: CardService, count: int, deck: str = DECK) -> list[int]:
    note_ids = []
    for index in range(count):
        front = f"#defn[{deck} {index}][meaning {index}]"
        note_ids.append(service.save(CardDraft(deck, "blank", (), front, f"back {index}")).note_id)
    return note_ids


def test_search_escaping() -> None:
    assert escape_search_text('a_b*c"d\\e') == 'a\\_b\\*c\\"d\\\\e'
    assert deck_exactly_terms("A_B") == '"deck:A\\_B" -"deck:A\\_B::*"'


def test_macro_change_marks_cards_stale_and_rerender_updates_all(
    service: CardService, fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki]
) -> None:
    _, fake = fake_ankiconnect
    note_ids = add_cards(service, 50)
    rerenderer = Rerenderer(service)
    assert rerenderer.staleness(DECK).stale_count == 0
    fake.notes[note_ids[0]].review_count = 3

    (service.library.root / MACROS).write_text("#let defn(term, body) = [_#term:_ #body]\n")
    staleness = rerenderer.staleness(DECK)
    assert staleness.stale_count == 50
    assert staleness.total == 50

    dry_run = rerenderer.run(staleness.stale_note_ids, apply=False)
    assert len(dry_run.compiled) == 50 and not dry_run.failures and not dry_run.updated
    assert rerenderer.staleness(DECK).stale_count == 50

    progress: list[RerenderProgress] = []
    applied = rerenderer.run(staleness.stale_note_ids, apply=True, progress=progress.append)
    assert len(applied.updated) == 50
    assert progress[-1] == RerenderProgress(done=50, total=50)
    assert rerenderer.staleness(DECK).stale_count == 0
    assert fake.notes[note_ids[0]].review_count == 3
    assert len(fake.notes) == 50


def test_broken_macro_is_reported_and_nothing_overwritten(
    service: CardService, fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki]
) -> None:
    _, fake = fake_ankiconnect
    add_cards(service, 50)
    before = {note_id: dict(note.fields) for note_id, note in fake.notes.items()}
    (service.library.root / MACROS).write_text("#let defn(term, body) = [#undefined-function(term)]\n")
    rerenderer = Rerenderer(service)
    staleness = rerenderer.staleness(DECK)
    dry_run = rerenderer.run(staleness.stale_note_ids, apply=False)
    assert len(dry_run.failures) == 50
    assert all(failure.diagnostics for failure in dry_run.failures)
    groups = group_failures(dry_run.failures)
    assert len(groups) == 1
    assert groups[0].diagnostic is not None and groups[0].diagnostic.file == MACROS
    assert len(groups[0].failures) == 50
    applied = rerenderer.run(staleness.stale_note_ids, apply=True)
    assert not applied.updated
    assert {note_id: note.fields for note_id, note in fake.notes.items()} == before


def test_staleness_scopes_to_deck_and_children_with_their_own_config(service: CardService) -> None:
    add_cards(service, 2)
    add_cards(service, 3, deck="Real Analysis::Topology")
    for index in range(4):
        service.save(CardDraft("Biology", "blank", (), f"cell {index}", "unit"))
    rerenderer = Rerenderer(service)
    topology = service.library.create_deck_folder("Real Analysis::Topology")
    assert rerenderer.staleness(DECK).stale_count == 0
    assert topology.folder is not None
    service.library.deck_file_path(topology.folder, "macros.typ").write_text(
        "#let defn(term, body) = [#body]\n"
    )
    report = rerenderer.staleness(DECK)
    assert {deck.deck_name: len(deck.stale_note_ids) for deck in report.decks} == {
        "Real Analysis": 0,
        "Real Analysis::Topology": 3,
    }
    assert report.total == 5
    (service.library.root / "global/macros.typ").write_text("#let RRR = 1\n")
    assert rerenderer.staleness(None).stale_count == 9


def test_partial_failure_updates_only_cards_that_compile(service: CardService) -> None:
    macros = "#let defn(term, body) = [*#term:* #body]\n#let special = [ok]\n"
    (service.library.root / MACROS).write_text(macros)
    good = add_cards(service, 3)
    bad = service.save(CardDraft(DECK, "blank", (), "#defn[Special][x]", "uses #special")).note_id
    rerenderer = Rerenderer(service)
    (service.library.root / MACROS).write_text("#let defn(term, body) = [*#term*. #body]\n")
    report = rerenderer.run(rerenderer.staleness(DECK).stale_note_ids, apply=True)
    assert sorted(report.updated) == sorted(good)
    assert [failure.note_id for failure in report.failures] == [bad]
    assert rerenderer.staleness(DECK).stale_note_ids == (bad,)


def test_cancel_stops_between_chunks(service: CardService) -> None:
    add_cards(service, 60)
    (service.library.root / MACROS).write_text("#let defn(term, body) = [#term -- #body]\n")
    rerenderer = Rerenderer(service)
    cancel = threading.Event()

    def cancel_after_first_chunk(progress: RerenderProgress) -> None:
        cancel.set()

    report = rerenderer.run(
        rerenderer.staleness(DECK).stale_note_ids,
        apply=True,
        progress=cancel_after_first_chunk,
        cancel=cancel,
    )
    assert report.cancelled
    assert len(report.updated) == 25
    assert rerenderer.staleness(DECK).stale_count == 35


def test_fields_written_by_rerender_match_fresh_save(service: CardService) -> None:
    note_id = add_cards(service, 1)[0]
    (service.library.root / MACROS).write_text("#let defn(term, body) = [#term: #body]\n")
    rerenderer = Rerenderer(service)
    rerenderer.run(rerenderer.staleness(DECK).stale_note_ids, apply=True)
    opened = service.open(note_id)
    assert not opened.stale and not opened.drifted
    assert opened.card.preamble_hash == service.library.resolve_deck(DECK).preamble.hash
    assert opened.card.renderer_version == service.renderer.renderer_version
    assert note_type.NOTE_TYPE_NAME

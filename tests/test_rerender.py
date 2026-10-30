import threading

from conftest import replace_defn

from typki.anki.ankiconnect import AnkiConnectGateway
from typki.anki.fake_anki import FakeAnki
from typki.anki.search import escape_search_text
from typki.card_service import CardService
from typki.domain.card import CardDraft
from typki.rerender.runner import Rerenderer, RerenderProgress

DECK = "Real Analysis"


def add_cards(service: CardService, count: int, deck: str = DECK) -> list[int]:
    note_ids = []
    for index in range(count):
        front = f"#defn[{deck} {index}][meaning {index}]"
        note_ids.append(service.save(CardDraft(deck, "blank", (), front, f"back {index}")).note_id)
    return note_ids


def test_search_escaping() -> None:
    assert escape_search_text('a_b*c"d\\e') == 'a\\_b\\*c\\"d\\\\e'


def test_header_change_marks_all_decks_stale_and_rerender_updates_all(
    service: CardService, fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki]
) -> None:
    _, fake = fake_ankiconnect
    note_ids = add_cards(service, 40) + add_cards(service, 10, deck="Biology")
    rerenderer = Rerenderer(service)
    assert rerenderer.staleness().stale_count == 0
    fake.notes[note_ids[0]].review_count = 3

    replace_defn(service.library, "#let defn(term, body) = [_#term:_ #body]")
    staleness = rerenderer.staleness()
    assert staleness.stale_count == 50
    assert staleness.total == 50

    dry_run = rerenderer.run(staleness.stale_note_ids, apply=False)
    assert len(dry_run.compiled) == 50 and not dry_run.failures and not dry_run.updated
    assert rerenderer.staleness().stale_count == 50

    progress: list[RerenderProgress] = []
    applied = rerenderer.run(staleness.stale_note_ids, apply=True, progress=progress.append)
    assert len(applied.updated) == 50
    assert progress[-1] == RerenderProgress(done=50, total=50)
    assert rerenderer.staleness().stale_count == 0
    assert fake.notes[note_ids[0]].review_count == 3
    assert len(fake.notes) == 50


def test_broken_header_blames_header_and_overwrites_nothing(
    service: CardService, fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki]
) -> None:
    _, fake = fake_ankiconnect
    add_cards(service, 50)
    before = {note_id: dict(note.fields) for note_id, note in fake.notes.items()}
    replace_defn(service.library, "#let defn(term, body) = [#undefined-function(term)]")
    rerenderer = Rerenderer(service)
    staleness = rerenderer.staleness()
    dry_run = rerenderer.run(staleness.stale_note_ids, apply=False)
    assert len(dry_run.failures) == 50
    assert all(
        any(diagnostic.file == "header.typ" for diagnostic in failure.diagnostics)
        for failure in dry_run.failures
    )
    applied = rerenderer.run(staleness.stale_note_ids, apply=True)
    assert not applied.updated
    assert {note_id: note.fields for note_id, note in fake.notes.items()} == before


def test_partial_failure_updates_only_cards_that_compile(service: CardService) -> None:
    service.library.write_header(service.library.read_header() + "#let special = [ok]\n")
    good = add_cards(service, 3)
    bad = service.save(CardDraft(DECK, "blank", (), "#defn[Special][x]", "uses #special")).note_id
    lines = [line for line in service.library.read_header().splitlines() if "special" not in line]
    service.library.write_header("\n".join(lines) + "\n")
    rerenderer = Rerenderer(service)
    report = rerenderer.run(rerenderer.staleness().stale_note_ids, apply=True)
    assert sorted(report.updated) == sorted(good)
    assert [failure.note_id for failure in report.failures] == [bad]
    assert rerenderer.staleness().stale_note_ids == (bad,)


def test_cancel_stops_between_chunks(service: CardService) -> None:
    add_cards(service, 60)
    replace_defn(service.library, "#let defn(term, body) = [#term -- #body]")
    rerenderer = Rerenderer(service)
    cancel = threading.Event()

    def cancel_after_first_chunk(progress: RerenderProgress) -> None:
        cancel.set()

    stale_ids = rerenderer.staleness().stale_note_ids
    report = rerenderer.run(stale_ids, apply=True, progress=cancel_after_first_chunk, cancel=cancel)
    assert report.cancelled
    assert len(report.updated) == 25
    assert rerenderer.staleness().stale_count == 35


def test_fields_written_by_rerender_match_fresh_save(service: CardService) -> None:
    note_id = add_cards(service, 1)[0]
    replace_defn(service.library, "#let defn(term, body) = [#term: #body]")
    rerenderer = Rerenderer(service)
    rerenderer.run(rerenderer.staleness().stale_note_ids, apply=True)
    opened = service.open(note_id)
    fresh = service.render(opened.front_source, opened.back_source)
    assert not service.is_stale(opened, service.library.preamble())
    assert (opened.front_svg, opened.back_svg) == (fresh.front.svg, fresh.back.svg)

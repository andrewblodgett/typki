from pathlib import Path

from typki.domain.card import CardDraft
from typki.domain.preamble import DEFAULT_HEADER
from typki.launcher import APP_ID, install_launcher
from typki.library.drafts import DraftStore
from typki.library.outbox import Outbox
from typki.library.store import Library


def test_new_library_gets_default_header(tmp_path: Path) -> None:
    library = Library(tmp_path / "fresh")
    library.ensure_layout()
    assert library.read_header() == DEFAULT_HEADER
    assert library.fonts_dir.is_dir()


def test_existing_header_is_never_overwritten(tmp_path: Path) -> None:
    library = Library(tmp_path)
    library.write_header("#set text(size: 9pt)\n")
    library.ensure_layout()
    assert library.read_header() == "#set text(size: 9pt)\n"


def test_editing_header_changes_hash(library: Library) -> None:
    before = library.preamble().hash
    library.write_header(library.read_header() + "#let other = 1\n")
    assert library.preamble().hash != before


def test_adding_a_font_changes_hash(library: Library) -> None:
    before = library.preamble().hash
    (library.fonts_dir / "Custom.ttf").write_bytes(b"not really a font")
    assert library.preamble().hash != before


def test_draft_round_trip(tmp_path: Path) -> None:
    store = DraftStore(tmp_path / "state" / "draft.json")
    assert store.load() is None
    draft = CardDraft("Deck", "definition", ("a", "b"), "front «x»", "back", note_id=42)
    store.save(draft)
    assert store.load() == draft


def test_outbox_keeps_latest_draft_per_card_in_order(tmp_path: Path) -> None:
    outbox = Outbox(tmp_path / "outbox")
    assert outbox.drafts() == [] and outbox.count() == 0
    first = CardDraft("Deck", "", (), "first", "")
    second = CardDraft("Deck", "", (), "second", "")
    outbox.put(first)
    outbox.put(second)
    outbox.put(CardDraft("Deck", "", (), "first edited", "", source_id=first.source_id))
    assert [draft.front for draft in outbox.drafts()] == ["second", "first edited"]
    outbox.remove(second.source_id)
    assert outbox.count() == 1


def test_launcher_entry_points_at_executable_and_ships_icon(tmp_path: Path) -> None:
    executable = tmp_path / "bin" / "typki"
    entry, icon = install_launcher(executable, tmp_path / "share")
    text = entry.read_text()
    assert entry == tmp_path / "share" / "applications" / "typki.desktop"
    assert f'Exec="{executable}"' in text
    assert f"Icon={APP_ID}" in text and f"StartupWMClass={APP_ID}" in text
    assert icon.read_text().startswith("<svg")

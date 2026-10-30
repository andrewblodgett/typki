from pathlib import Path

from typki.domain.card import CardDraft
from typki.domain.preamble import DEFAULT_HEADER
from typki.library.drafts import DraftStore
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

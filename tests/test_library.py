from pathlib import Path

from typki.domain.card import CardDraft
from typki.library.drafts import DraftStore
from typki.library.store import Library


def test_resolves_configured_deck_and_child(library: Library) -> None:
    resolved = library.resolve_deck("Real Analysis::Theorems")
    assert resolved.config.folder == "real-analysis"
    assert resolved.config.scale == 1.25
    assert '#import "/decks/real-analysis/style.typ": card-style' in resolved.preamble.header


def test_unconfigured_deck_gets_defaults_with_global_macros(library: Library) -> None:
    resolved = library.resolve_deck("Biology")
    assert resolved.config.folder is None
    assert '#import "/global/macros.typ": *' in resolved.preamble.header
    assert "card-style" not in resolved.preamble.header


def test_editing_macros_changes_hash(library: Library) -> None:
    before = library.resolve_deck("Real Analysis").preamble.hash
    (library.root / "decks/real-analysis/macros.typ").write_text("#let other = 1\n")
    assert library.resolve_deck("Real Analysis").preamble.hash != before


def test_invalid_deck_config_is_reported_not_raised(library: Library) -> None:
    broken = library.root / "decks/broken"
    broken.mkdir()
    (broken / "deck.toml").write_text("scale = 'big'\n")
    configs, problems = library.deck_configs()
    assert "Real Analysis" in configs
    assert any("decks/broken" in problem for problem in problems)


def test_draft_round_trip(tmp_path: Path) -> None:
    store = DraftStore(tmp_path / "state" / "draft.json")
    assert store.load() is None
    draft = CardDraft("Deck", "definition", ("a", "b"), "front «x»", "back", note_id=42)
    store.save(draft)
    assert store.load() == draft

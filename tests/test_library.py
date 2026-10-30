import tomllib
from pathlib import Path

from typki.domain.card import CardDraft
from typki.library.deck_config import update_toml_keys
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


def test_update_toml_keys_preserves_comments_and_unknown_keys() -> None:
    original = "# my deck\nanki_deck = 'X'\ncustom = 1\nscale = 2.0\n"
    updated = update_toml_keys(original, {"scale": 1.5, "fit_width": False, "default_tags": ["a", "b"]})
    assert updated.startswith("# my deck\nanki_deck = 'X'\ncustom = 1\nscale = 1.5\n")
    assert tomllib.loads(updated) == {
        "anki_deck": "X",
        "custom": 1,
        "scale": 1.5,
        "fit_width": False,
        "default_tags": ["a", "b"],
    }


def test_create_deck_folder_for_unconfigured_deck(library: Library) -> None:
    config = library.create_deck_folder("Biology::Cells")
    assert config.folder == "biology-cells"
    assert library.resolve_deck("Biology::Cells").config == config
    assert "card-style" in library.read_text(library.deck_file_path("biology-cells", "style.typ"))
    assert library.resolve_deck("Biology::Cells").preamble.header.count("#import") == 3


def test_create_deck_folder_copies_inherited_style(library: Library) -> None:
    parent_before = library.resolve_deck("Real Analysis")
    config = library.create_deck_folder("Real Analysis::Theorems")
    assert config.folder == "real-analysis-theorems"
    assert config.scale == parent_before.config.scale
    copied_macros = library.read_text(library.deck_file_path("real-analysis-theorems", "macros.typ"))
    assert "defn" in copied_macros
    assert library.resolve_deck("Real Analysis").config == parent_before.config


def test_folder_names_are_unique(library: Library) -> None:
    library.deck_folder_path("biology").mkdir()
    assert library.create_deck_folder("Biology").folder == "biology-2"


def test_write_deck_settings_round_trips(library: Library) -> None:
    config = library.resolve_deck("Real Analysis").config
    from dataclasses import replace

    changed = replace(config, scale=2.0, fit_width=False, default_tags=("x",))
    library.write_deck_settings(changed)
    assert library.resolve_deck("Real Analysis").config == changed


def test_copying_inherited_style_keeps_cards_fresh(library: Library) -> None:
    parent_hash = library.resolve_deck("Real Analysis::Theorems").preamble.hash
    library.create_deck_folder("Real Analysis::Theorems")
    assert library.resolve_deck("Real Analysis::Theorems").preamble.hash == parent_hash

from typki.domain.card import parse_tags
from typki.domain.deck import (
    DeckConfig,
    ancestor_deck_names,
    deck_slug,
    is_same_or_descendant,
    length_to_mm,
    resolve_deck_config,
)
from typki.domain.preamble import PreambleFiles, build_preamble, build_preamble_header
from typki.domain.staleness import is_stale
from typki.domain.template import BUILT_IN_TEMPLATES, find_template, placeholder_spans


def test_ancestor_deck_names_from_most_to_least_specific() -> None:
    assert ancestor_deck_names("A::B::C") == ["A::B::C", "A::B", "A"]


def test_child_deck_inherits_nearest_configured_ancestor() -> None:
    parent = DeckConfig(anki_deck="Real Analysis", page_width="90mm")
    child = DeckConfig(anki_deck="Real Analysis::Theorems", page_width="70mm")
    configs = {parent.anki_deck: parent, child.anki_deck: child}
    assert resolve_deck_config("Real Analysis::Theorems::Hard", configs) is child
    assert resolve_deck_config("Real Analysis::Examples", configs) is parent
    assert resolve_deck_config("Other", configs) == DeckConfig(anki_deck="Other")


def test_fit_width_header_caps_at_page_width() -> None:
    header = build_preamble_header(DeckConfig(anki_deck="D", page_width="90mm"), PreambleFiles())
    assert "width: auto" in header.splitlines()[0]
    assert "calc.min(natural-width, 90mm)" in header


def test_header_imports_in_order_and_applies_style() -> None:
    header = build_preamble_header(
        DeckConfig(anki_deck="D", page_width="90mm", fit_width=False),
        PreambleFiles("/global/macros.typ", "/decks/d/macros.typ", "/decks/d/style.typ"),
    )
    lines = header.splitlines()
    assert "width: 90mm" in lines[0]
    assert lines[2:] == [
        '#import "/global/macros.typ": *',
        '#import "/decks/d/macros.typ": *',
        '#import "/decks/d/style.typ": card-style',
        "#show: card-style",
    ]


def test_preamble_hash_changes_with_inputs() -> None:
    config = DeckConfig(anki_deck="D")
    files = PreambleFiles(global_macros="/global/macros.typ")
    base = build_preamble(config, files, {"/global/macros.typ": b"a"}, "fonts1")
    assert base.hash == build_preamble(config, files, {"/global/macros.typ": b"a"}, "fonts1").hash
    assert base.hash != build_preamble(config, files, {"/global/macros.typ": b"b"}, "fonts1").hash
    assert base.hash != build_preamble(config, files, {"/global/macros.typ": b"a"}, "fonts2").hash
    rescaled = DeckConfig(anki_deck="D", scale=2.0)
    assert base.hash != build_preamble(rescaled, files, {"/global/macros.typ": b"a"}, "fonts1").hash


def test_staleness() -> None:
    assert not is_stale("h", "v", "h", "v")
    assert is_stale("h", "v", "h2", "v")
    assert is_stale("h", "v", "h", "v2")


def test_templates_and_placeholders() -> None:
    assert find_template("definition").title == "Definition"
    assert find_template("missing").key == "blank"
    assert len({template.key for template in BUILT_IN_TEMPLATES}) == len(BUILT_IN_TEMPLATES)
    text = find_template("definition").back
    assert [text[start:end] for start, end in placeholder_spans(text)] == ["«term»", "«definition»"]


def test_parse_tags_deduplicates_and_keeps_order() -> None:
    assert parse_tags(" b a  b c ") == ("b", "a", "c")


def test_length_conversion_and_slugs() -> None:
    assert length_to_mm("80mm") == 80
    assert length_to_mm("8 cm") == 80
    assert length_to_mm("1in") == 25.4
    assert length_to_mm("80%") is None
    assert deck_slug("Real Analysis::Theorems") == "real-analysis-theorems"
    assert deck_slug("::") == "deck"


def test_descendant_check() -> None:
    assert is_same_or_descendant("A::B", "A")
    assert is_same_or_descendant("A", "A")
    assert not is_same_or_descendant("AB", "A")

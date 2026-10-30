from typki.domain.card import parse_tags
from typki.domain.preamble import build_preamble
from typki.domain.staleness import is_stale
from typki.domain.template import BUILT_IN_TEMPLATES, find_template, placeholder_spans


def test_preamble_header_ends_with_newline_and_counts_lines() -> None:
    preamble = build_preamble("#set text(size: 12pt)", "")
    assert preamble.header == "#set text(size: 12pt)\n"
    assert preamble.line_count == 1
    assert preamble.wrap("card") == "#set text(size: 12pt)\ncard"


def test_preamble_hash_changes_with_header_and_fonts() -> None:
    base = build_preamble("a", "fonts1")
    assert base.hash == build_preamble("a\n", "fonts1").hash
    assert base.hash != build_preamble("b", "fonts1").hash
    assert base.hash != build_preamble("a", "fonts2").hash


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

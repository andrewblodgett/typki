from typki.domain.card import parse_tags
from typki.domain.preamble import DEFAULT_HEADER, build_preamble
from typki.domain.staleness import is_stale
from typki.domain.template import BLANK, find_template, placeholder_spans, templates_from_header


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


def test_templates_come_from_header_functions() -> None:
    header = """#set text(size: 12pt)
#let RR = $bb(R)$
#let theorem(name, statement) = [*Theorem* (#name). #statement]
#let lemma(body, numbered: true) = [*Lemma.* #body]
#let qed() = [∎]
  #let indented(x) = x
#let theorem(other) = [duplicate]
"""
    templates = templates_from_header(header)
    assert [template.title for template in templates] == ["Blank", "theorem", "lemma", "qed"]
    assert find_template("theorem", templates).front == "#theorem[«name»][«statement»]"
    assert find_template("lemma", templates).front == "#lemma[«body»]"
    assert find_template("qed", templates).front == "#qed()"
    assert find_template("missing", templates) is BLANK


def test_default_header_ships_definition_and_theorem() -> None:
    names = [template.name for template in templates_from_header(DEFAULT_HEADER)]
    assert names == ["", "definition", "theorem"]


def test_placeholder_spans() -> None:
    text = "#definition[«term»][«body»]"
    assert [text[start:end] for start, end in placeholder_spans(text)] == ["«term»", "«body»"]


def test_parse_tags_deduplicates_and_keeps_order() -> None:
    assert parse_tags(" b a  b c ") == ("b", "a", "c")

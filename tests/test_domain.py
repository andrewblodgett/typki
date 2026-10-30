from typki.domain.card import missing_content, parse_tags
from typki.domain.preamble import DEFAULT_HEADER, build_preamble
from typki.domain.staleness import is_stale
from typki.domain.template import (
    BLANK,
    find_template,
    placeholder_spans,
    retag_for_template,
    template_for_tags,
    templates_from_header,
)


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


def test_capitalized_header_functions_are_templates() -> None:
    header = """#set text(size: 12pt)
#let RR = $bb(R)$
#let Theorem(name, statement) = [*Theorem* (#name). #statement]
#let Lemma(body, numbered: true) = [*Lemma.* #body]
#let Qed() = [∎]
#let proof(body) = [_Proof._ #body]
#let vb(x) = math.upright(math.bold(x))
  #let Indented(x) = x
#let Theorem(other) = [duplicate]
"""
    templates = templates_from_header(header)
    assert [template.title for template in templates] == ["Blank", "Theorem", "Lemma", "Qed"]
    assert find_template("Theorem", templates).front == "#Theorem[«name»][«statement»]"
    assert find_template("Lemma", templates).front == "#Lemma[«body»]"
    assert find_template("Qed", templates).front == "#Qed()"
    assert find_template("proof", templates) is BLANK


def test_default_header_ships_definition_and_theorem() -> None:
    names = [template.name for template in templates_from_header(DEFAULT_HEADER)]
    assert names == ["", "Definition", "Theorem"]


def test_choosing_a_template_swaps_its_tag() -> None:
    templates = templates_from_header(DEFAULT_HEADER)
    theorem = find_template("Theorem", templates)
    definition = find_template("Definition", templates)
    assert retag_for_template(("analysis",), theorem, templates) == ("analysis", "Theorem")
    assert retag_for_template(("analysis", "Theorem"), definition, templates) == ("analysis", "Definition")
    assert retag_for_template(("Theorem", "analysis"), theorem, templates) == ("analysis", "Theorem")
    assert retag_for_template(("analysis", "Definition"), BLANK, templates) == ("analysis",)
    assert template_for_tags(("analysis", "Theorem"), templates) == theorem
    assert template_for_tags(("analysis",), templates) is BLANK


def test_placeholder_spans() -> None:
    text = "#Definition[«term»][«body»]"
    assert [text[start:end] for start, end in placeholder_spans(text)] == ["«term»", "«body»"]


def test_parse_tags_deduplicates_and_keeps_order() -> None:
    assert parse_tags(" b a  b c ") == ("b", "a", "c")


def test_cards_need_front_back_and_filled_placeholders() -> None:
    assert missing_content("", "answer") == "The front is empty"
    assert missing_content("question", "  \n") == "The back is empty"
    assert missing_content("#defn[«term»][x]", "answer") == "Fill in the «» placeholders"
    assert missing_content("question", "answer") is None

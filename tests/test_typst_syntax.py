import pytest

from typki.typst_syntax.catalog import Catalog, Entry, parse_variants, typst_catalog
from typki.typst_syntax.completion import complete, header_definitions
from typki.typst_syntax.editing import (
    Edit,
    delete_backward,
    delete_lines,
    duplicate_lines,
    indent_lines,
    insert_newline,
    move_lines,
    outdent_lines,
    select_lines,
    smart_home,
    toggle_line_comment,
    type_character,
)
from typki.typst_syntax.lexer import Kind, Mode, lex

HEADER = "#let RR = $bb(R)$\n#let defn(term, body) = [*#term.* #body]\n"


def kinds_of(text: str) -> list[tuple[Kind, str]]:
    return [(token.kind, text[token.start : token.end]) for token in lex(text).tokens]


def apply(text: str, edit: Edit | None) -> tuple[str, int, int]:
    assert edit is not None
    return text[: edit.start] + edit.replacement + text[edit.end :], edit.selection_start, edit.selection_end


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    return typst_catalog()


def test_lexer_tracks_math_code_and_markup_modes() -> None:
    text = "Let $alpha -> RR$ and #defn[term][body] then #set text(red) tail"
    lexed = lex(text)
    assert lexed.mode_at(text.index("alpha")) == Mode.MATH
    assert lexed.mode_at(text.index("term")) == Mode.MARKUP
    assert lexed.mode_at(text.index("red")) == Mode.CODE
    assert lexed.mode_at(text.index("tail")) == Mode.MARKUP


def test_lexer_classifies_typst_constructs() -> None:
    tokens = kinds_of('= Title\n*bold* $frac(a, b)^2$ // note\n#let x = "s"\nSee <lbl> @ref')
    assert (Kind.HEADING, "= Title") in tokens
    assert (Kind.STRONG, "bold") in tokens
    assert (Kind.FUNCTION, "frac") in tokens
    assert (Kind.MATH_OPERATOR, "^") in tokens
    assert (Kind.COMMENT, "// note") in tokens
    assert (Kind.KEYWORD, "#let") in tokens
    assert (Kind.STRING, '"s"') in tokens
    assert (Kind.LABEL, "<lbl>") in tokens
    assert (Kind.REFERENCE, "@ref") in tokens


def test_lexer_keeps_symbol_variants_together_and_ignores_snake_case() -> None:
    assert (Kind.MATH_SYMBOL, "arrow.r.double") in kinds_of("$arrow.r.double$")
    assert not any(kind == Kind.EMPH for kind, _ in kinds_of("snake_case_name"))


def test_lexer_survives_unterminated_input() -> None:
    for text in ("$x", "#f(", "#[abc", '#let s = "x', "/* open", "```py", "#"):
        lex(text)


def test_catalog_lists_symbols_with_variants(catalog: Catalog) -> None:
    arrow = catalog.module("sym")["arrow"]
    assert arrow.glyph == "→"
    assert ("r.double", "⇒") in arrow.variants
    assert catalog.module("math")["frac"].callable


def test_variant_glyph_escapes_are_decoded() -> None:
    assert parse_variants('symbol(("r", "\\u{2192}"))') == (("r", "→"),)


def test_math_completion_offers_functions_with_parentheses(catalog: Catalog) -> None:
    result = complete("$fr", 3, catalog)
    assert result is not None
    frac = next(item for item in result.items if item.label == "frac")
    assert (result.replace_start, frac.insert, frac.cursor_offset) == (1, "frac()", 5)


def test_math_completion_needs_two_letters_unless_requested(catalog: Catalog) -> None:
    assert complete("$a", 2, catalog) is None
    assert complete("$a", 2, catalog, explicit=True) is not None


def test_symbol_variants_complete_after_dot(catalog: Catalog) -> None:
    result = complete("$arrow.r.do", 11, catalog)
    assert result is not None
    assert result.replace_start == 7
    assert [item.label for item in result.items][:3] == ["r.dotted", "r.double", "r.double.bar"]
    assert result.items[1].detail == "⇒"


def test_hash_completion_puts_header_definitions_first(catalog: Catalog) -> None:
    result = complete("#", 1, catalog, HEADER)
    assert result is not None
    assert {item.label for item in result.items[:2]} == {"RR", "defn"}
    defn = next(item for item in result.items if item.label == "defn")
    assert defn.detail == "(term, body)"


def test_module_members_complete_in_code(catalog: Catalog) -> None:
    result = complete("#calc.po", 8, catalog)
    assert result is not None
    assert result.items[0].insert == "pow()"


def test_plain_markup_does_not_complete(catalog: Catalog) -> None:
    assert complete("some te", 7, catalog) is None


def test_fully_typed_symbol_closes_completion(catalog: Catalog) -> None:
    assert complete("$alpha", 6, catalog) is None


def test_header_definitions_include_values_and_functions() -> None:
    labels = {item.label: item.kind for item in header_definitions(HEADER)}
    assert labels == {"RR": "variable", "defn": "function"}


def test_brackets_and_dollars_autoclose() -> None:
    assert apply("", type_character("", 0, 0, "(", Mode.MARKUP)) == ("()", 1, 1)
    assert apply("", type_character("", 0, 0, "$", Mode.MARKUP)) == ("$$", 1, 1)
    assert apply("a ", type_character("a ", 2, 2, "[", Mode.MARKUP)) == ("a []", 3, 3)


def test_autoclose_skips_before_words_and_after_backslash() -> None:
    assert type_character("x", 0, 0, "(", Mode.MARKUP) is None
    assert type_character("\\", 1, 1, "$", Mode.MARKUP) is None
    assert type_character("", 0, 0, '"', Mode.MARKUP) is None


def test_closers_type_over_existing_closers() -> None:
    assert apply("()", type_character("()", 1, 1, ")", Mode.CODE)) == ("()", 2, 2)
    assert apply("$x$", type_character("$x$", 2, 2, "$", Mode.MATH)) == ("$x$", 3, 3)


def test_selection_gets_wrapped() -> None:
    assert apply("word", type_character("word", 0, 4, "$", Mode.MARKUP)) == ("$word$", 1, 5)
    assert apply("word", type_character("word", 0, 4, "*", Mode.MARKUP)) == ("*word*", 1, 5)


def test_backspace_removes_empty_pair() -> None:
    assert apply("a()", delete_backward("a()", 2, 2)) == ("a", 1, 1)
    assert delete_backward("a(x)", 2, 2) is None


def test_enter_keeps_indent_and_splits_brackets() -> None:
    assert apply("  x", insert_newline("  x", 3, 3)) == ("  x\n  ", 6, 6)
    assert apply("f[]", insert_newline("f[]", 2, 2)) == ("f[\n  \n]", 5, 5)


def test_toggle_comment_round_trips() -> None:
    text = "a\n  b\n"
    commented = apply(text, toggle_line_comment(text, 0, 4))
    assert commented[0] == "// a\n//   b\n"
    assert apply(commented[0], toggle_line_comment(commented[0], 0, 8))[0] == text


def test_move_and_duplicate_lines() -> None:
    assert apply("a\nb\nc", move_lines("a\nb\nc", 2, 2, upward=True)) == ("b\na\nc", 0, 0)
    assert apply("a\nb\nc", move_lines("a\nb\nc", 2, 2, upward=False)) == ("a\nc\nb", 4, 4)
    assert move_lines("a\nb", 0, 0, upward=True) is None
    assert apply("a\nb", duplicate_lines("a\nb", 0, 0, upward=False)) == ("a\na\nb", 2, 2)


def test_delete_lines_and_select_lines() -> None:
    assert apply("a\nbc\nd", delete_lines("a\nbc\nd", 3, 3))[0] == "a\nd"
    assert apply("a\nb", delete_lines("a\nb", 2, 2))[0] == "a"
    assert select_lines("a\nb\nc", 0, 0) == (0, 2)
    assert select_lines("a\nb\nc", 0, 2) == (0, 4)


def test_indent_outdent_and_smart_home() -> None:
    assert apply("a\nb", indent_lines("a\nb", 0, 3))[0] == "  a\n  b"
    assert apply("  a\n b", outdent_lines("  a\n b", 0, 6))[0] == "a\nb"
    assert smart_home("  abc", 4) == 2
    assert smart_home("  abc", 2) == 0


def test_keywords_complete_with_a_minimal_catalog() -> None:
    catalog = Catalog({"std": {"text": Entry("text", "function")}})
    result = complete("#le", 3, catalog)
    assert result is not None
    assert result.items[0].insert == "let "

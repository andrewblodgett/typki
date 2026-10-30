import re
from pathlib import Path

from typki.domain.deck import DeckConfig
from typki.domain.preamble import Preamble, PreambleFiles, build_preamble
from typki.library.store import Library
from typki.render.compiler import Renderer
from typki.render.diagnostics import parse_diagnostics
from typki.render.plain_text import plain_text_from_source
from typki.render.svg_postprocess import postprocess_svg

MINIMAL_SVG = (
    b'<svg viewBox="0 0 100 50" width="100pt" height="50pt" xmlns="http://www.w3.org/2000/svg">'
    b'<path fill="#000000" stroke="#000000" d="M0 0"/><path fill="#ff0000" d="M1 1"/></svg>'
)


def deck_preamble(library: Library) -> Preamble:
    return library.resolve_deck("Real Analysis").preamble


def test_postprocess_themes_scales_and_describes() -> None:
    result = postprocess_svg(MINIMAL_SVG, "a < b & c", 1.5)
    assert result == (
        '<svg viewBox="0 0 100 50" width="150.000pt" height="75.000pt" xmlns="http://www.w3.org/2000/svg">'
        "<desc>a &lt; b &amp; c</desc>"
        '<path fill="currentColor" stroke="currentColor" d="M0 0"/><path fill="#ff0000" d="M1 1"/></svg>'
    )


def test_plain_text_strips_markup_and_code() -> None:
    source = '#import "@preview/x:0.1.0"\n// note\n*Define* «term» $x in RR$ #defn[Term][body]'
    assert plain_text_from_source(source) == "Define term x in RR Term body"


def test_plain_text_falls_back_to_source_when_only_code() -> None:
    assert plain_text_from_source("#line(length: 1cm)") != ""


def test_render_uses_global_and_deck_macros(library: Library, renderer: Renderer) -> None:
    result = renderer.render_side("#defn[Field][$RRR$ is complete]", deck_preamble(library))
    assert result.ok, result.diagnostics
    assert result.svg is not None
    assert "<desc>" in result.svg
    assert 'fill="#000000"' not in result.svg
    assert 'fill="currentColor"' in result.svg


def test_render_is_deterministic_across_compilers(library: Library, renderer: Renderer) -> None:
    preamble = deck_preamble(library)
    other = Renderer(library.root, [library.fonts_dir])
    source = "$ integral_0^1 x^2 dif x = 1/3 $"
    assert renderer.render_side(source, preamble).svg == other.render_side(source, preamble).svg


def test_card_error_reported_at_card_line(library: Library, renderer: Renderer) -> None:
    result = renderer.render_side("fine line\n$ undefinedthing(x) $", deck_preamble(library))
    assert not result.ok
    error = result.errors[0]
    assert error.in_card
    assert (error.line, error.column) == (2, 3)
    assert "unknown variable" in error.message


def test_macro_file_error_reported_in_that_file(library: Library, renderer: Renderer) -> None:
    (library.root / "decks/real-analysis/macros.typ").write_text("#let broken = (\n")
    result = renderer.render_side("hello", deck_preamble(library))
    assert not result.ok
    assert result.errors[0].file == "decks/real-analysis/macros.typ"


def test_picks_up_macro_changes_with_same_compiler(library: Library, renderer: Renderer) -> None:
    first = renderer.render_side("$RRR$", deck_preamble(library)).svg
    (library.root / "global/macros.typ").write_text("#let RRR = $bb(C)$\n")
    second = renderer.render_side("$RRR$", deck_preamble(library)).svg
    assert first != second


def test_page_width_from_deck_config(tmp_path: Path) -> None:
    library = Library(tmp_path)
    library.ensure_layout()
    narrow = build_preamble(DeckConfig("D", page_width="50mm", scale=1.0), PreambleFiles(), {}, "")
    wide = build_preamble(DeckConfig("D", page_width="100mm", scale=1.0), PreambleFiles(), {}, "")
    renderer = Renderer(library.root, [])
    width_pattern = re.compile(r'width="([\d.]+)pt"')

    def width_of(preamble: Preamble) -> float:
        svg = renderer.render_side("x", preamble).svg
        assert svg is not None
        match = width_pattern.search(svg)
        assert match is not None
        return float(match.group(1))

    assert width_of(wide) > width_of(narrow) * 1.9


def test_parse_diagnostics_without_location_uses_fallback(tmp_path: Path) -> None:
    diagnostics = parse_diagnostics("", "something failed", "error", 4, tmp_path)
    assert diagnostics[0].message == "something failed"
    assert diagnostics[0].line is None

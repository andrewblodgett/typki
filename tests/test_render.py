import re
from pathlib import Path

from typki.domain.preamble import DEFAULT_HEADER, Preamble, build_preamble
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
    return library.preamble()


def test_postprocess_themes_and_describes() -> None:
    result = postprocess_svg(MINIMAL_SVG, "a < b & c")
    assert result == (
        '<svg viewBox="0 0 100 50" width="100pt" height="50pt" xmlns="http://www.w3.org/2000/svg">'
        "<desc>a &lt; b &amp; c</desc>"
        '<path fill="currentColor" stroke="currentColor" d="M0 0"/><path fill="#ff0000" d="M1 1"/></svg>'
    )


def test_plain_text_strips_markup_and_code() -> None:
    source = '#import "@preview/x:0.1.0"\n// note\n*Define* «term» $x in RR$ #defn[Term][body]'
    assert plain_text_from_source(source) == "Define term x in RR Term body"


def test_plain_text_keeps_math_operators_and_drops_line_markers() -> None:
    source = "= Heading\n+ first item\n- second\n$x^2 >= 0$ and $a + b = c$"
    assert plain_text_from_source(source) == "Heading first item second x 2 >= 0 and a + b = c"


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


def test_header_error_reported_in_header(library: Library, renderer: Renderer) -> None:
    library.write_header("#set text(size: 12pt)\n#let broken = (\n")
    result = renderer.render_side("hello", deck_preamble(library))
    assert not result.ok
    assert result.errors[0].file == "header.typ"
    assert result.errors[0].line == 2


def test_picks_up_macro_changes_with_same_compiler(library: Library, renderer: Renderer) -> None:
    first = renderer.render_side("$RRR$", deck_preamble(library)).svg
    library.write_header(library.read_header().replace("bb(R)", "bb(C)"))
    second = renderer.render_side("$RRR$", deck_preamble(library)).svg
    assert first != second


def test_parse_diagnostics_without_location_uses_fallback(tmp_path: Path) -> None:
    diagnostics = parse_diagnostics("", "something failed", "error", 4, tmp_path)
    assert diagnostics[0].message == "something failed"
    assert diagnostics[0].line is None


def test_default_header_shrinks_short_cards_and_wraps_long_ones(tmp_path: Path) -> None:
    library = Library(tmp_path)
    library.ensure_layout()
    renderer = Renderer(library.root, [])
    preamble = build_preamble(DEFAULT_HEADER, "")
    width_pattern = re.compile(r'width="([\d.]+)pt"')

    def width_of(source: str) -> float:
        svg = renderer.render_side(source, preamble).svg
        assert svg is not None
        match = width_pattern.search(svg)
        assert match is not None
        return float(match.group(1))

    full_width_pt = 120 * 72 / 25.4 + 2 * 6
    assert width_of("Short.") < full_width_pt / 3
    assert abs(width_of("word " * 80) - full_width_pt) < 1

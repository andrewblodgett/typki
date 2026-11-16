import re
from importlib.metadata import version

from typki.anki import note_type
from typki.anki.gateway import AnkiError, AnkiGateway
from typki.card_service import note_type_query
from typki.library.store import HeaderMissingError, Library
from typki.render.compiler import Renderer

RECENT_NOTES = 3
SOURCE_PREVIEW_LENGTH = 100
SVG_ROOT = re.compile(r'<svg viewBox="0 0 ([\d.]+) ([\d.]+)"')
WHITE_FILL = 'fill="#ffffff"'
TEST_CARD = "test $x^2$"


def describe_svg(svg: str | None) -> str:
    if not svg:
        return "nothing"
    root = SVG_ROOT.match(svg)
    if root is None:
        return f"not a Typki SVG, starts {svg[:60]!r}"
    width, height = float(root[1]), float(root[2])
    return f"{width:.0f}x{height:.0f}pt, white fill: {WHITE_FILL in svg}, {len(svg)} characters"


def header_section(library: Library) -> list[str]:
    if not library.header_path.is_file():
        return [f"header: {library.header_path} is MISSING"]
    header = library.read_header()
    return [
        f"header: {library.header_path} ({len(header)} characters)",
        header.rstrip("\n"),
        "(end of header)",
    ]


def anki_section(library: Library, gateway: AnkiGateway, renderer: Renderer) -> list[str]:
    preamble = library.preamble()
    lines = [
        f"compiled now, test card: {describe_svg(renderer.render_side(TEST_CARD, preamble).svg)}",
        f"current header hash: {preamble.hash}, renderer: {renderer.renderer_version}",
    ]
    note_ids = sorted(gateway.find_notes(note_type_query()), reverse=True)
    lines.append(f"Typki notes in Anki: {len(note_ids)}")
    for record in gateway.notes_info(note_ids[:RECENT_NOTES]):
        fields = record.fields
        source = fields.get(note_type.FRONT_SOURCE, "")
        fresh = renderer.render_side(source, preamble)
        lines += [
            f"note {record.note_id} in {record.deck_name!r}",
            f"  front source: {source[:SOURCE_PREVIEW_LENGTH]!r}",
            f"  stored in Anki: {describe_svg(fields.get(note_type.FRONT))}",
            f"  stored with: {fields.get(note_type.PREAMBLE_HASH)}, {fields.get(note_type.RENDERER_VERSION)}",
            f"  compiled now: {describe_svg(fresh.svg)}, errors: {[error.message for error in fresh.errors]}",
        ]
    return lines


def diagnostic_report(library: Library, gateway: AnkiGateway) -> str:
    lines = [
        f"typst {version('typst')}, PySide6 {version('PySide6-Essentials')}",
        f"library: {library.root}",
        *header_section(library),
    ]
    try:
        lines += anki_section(library, gateway, Renderer(library.root, [library.fonts_dir]))
    except (AnkiError, HeaderMissingError) as error:
        lines.append(f"stopped: {error}")
    return "\n".join(lines)

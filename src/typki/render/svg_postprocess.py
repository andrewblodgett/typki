import re
from xml.sax.saxutils import escape

TYPST_BLACK = re.compile(r'(fill|stroke)="#000000"')
POINT_DIMENSION = re.compile(r'\b(width|height)="([\d.]+)pt"')


def theme_colors(svg_text: str) -> str:
    return TYPST_BLACK.sub(r'\1="currentColor"', svg_text)


def scale_dimensions(opening_tag: str, scale: float) -> str:
    def scaled(match: re.Match[str]) -> str:
        return f'{match.group(1)}="{float(match.group(2)) * scale:.3f}pt"'

    return POINT_DIMENSION.sub(scaled, opening_tag)


def postprocess_svg(svg_bytes: bytes, plain_text: str, scale: float) -> str:
    svg_text = theme_colors(svg_bytes.decode())
    opening_tag_end = svg_text.index(">") + 1
    opening_tag = scale_dimensions(svg_text[:opening_tag_end], scale)
    description = f"<desc>{escape(plain_text)}</desc>" if plain_text else ""
    return opening_tag + description + svg_text[opening_tag_end:]


def svg_for_display(svg_text: str, color: str) -> str:
    return svg_text.replace('"currentColor"', f'"{color}"')

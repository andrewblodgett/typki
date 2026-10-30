import re
from xml.sax.saxutils import escape

TYPST_BLACK = re.compile(r'(fill|stroke)="#000000"')


def theme_colors(svg_text: str) -> str:
    return TYPST_BLACK.sub(r'\1="currentColor"', svg_text)


def postprocess_svg(svg_bytes: bytes, plain_text: str) -> str:
    svg_text = theme_colors(svg_bytes.decode())
    opening_tag_end = svg_text.index(">") + 1
    description = f"<desc>{escape(plain_text)}</desc>" if plain_text else ""
    return svg_text[:opening_tag_end] + description + svg_text[opening_tag_end:]


def svg_for_display(svg_text: str, color: str) -> str:
    return svg_text.replace('"currentColor"', f'"{color}"')

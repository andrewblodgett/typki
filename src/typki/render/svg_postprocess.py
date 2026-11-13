import re
from xml.sax.saxutils import escape

TYPST_BLACK = re.compile(r'(fill|stroke)="#000000"')
COLOR_WITH_ALPHA = re.compile(r'(fill|stroke)="(#[0-9a-fA-F]{6})([0-9a-fA-F]{2})"')


def theme_colors(svg_text: str) -> str:
    return TYPST_BLACK.sub(r'\1="currentColor"', svg_text)


def postprocess_svg(svg_bytes: bytes, plain_text: str) -> str:
    svg_text = theme_colors(svg_bytes.decode())
    opening_tag_end = svg_text.index(">") + 1
    description = f"<desc>{escape(plain_text)}</desc>" if plain_text else ""
    return svg_text[:opening_tag_end] + description + svg_text[opening_tag_end:]


def split_alpha(match: re.Match[str]) -> str:
    attribute, color, alpha = match.groups()
    return f'{attribute}="{color}" {attribute}-opacity="{int(alpha, 16) / 255:.3f}"'


def svg_for_display(svg_text: str, color: str) -> str:
    themed = svg_text.replace('"currentColor"', f'"{color}"')
    # Qt's SVG renderer paints #rrggbbaa colors solid black, so the alpha moves to its own attribute.
    return COLOR_WITH_ALPHA.sub(split_alpha, themed)

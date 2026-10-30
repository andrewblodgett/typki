import hashlib
from collections.abc import Mapping
from dataclasses import dataclass

from typki.domain.deck import DeckConfig

PREAMBLE_FORMAT_VERSION = 1
PAGE_MARGIN = "5mm"
DEFAULT_FONTS = ("Libertinus Serif", "New Computer Modern")
DEFAULT_TEXT_SIZE = "11pt"
CARD_STYLE_FUNCTION = "card-style"


@dataclass(frozen=True)
class PreambleFiles:
    global_macros: str | None = None
    deck_macros: str | None = None
    deck_style: str | None = None

    def paths(self) -> list[str]:
        return [path for path in (self.global_macros, self.deck_macros, self.deck_style) if path]


@dataclass(frozen=True)
class Preamble:
    header: str
    hash: str
    scale: float

    @property
    def line_count(self) -> int:
        return self.header.count("\n")

    def wrap(self, card_source: str) -> str:
        return self.header + card_source


def build_preamble_header(config: DeckConfig, files: PreambleFiles) -> str:
    font_list = ", ".join(f'"{font}"' for font in DEFAULT_FONTS)
    lines = [
        f"#set page(width: {config.page_width}, height: auto, margin: {PAGE_MARGIN}, fill: none)",
        f"#set text(font: ({font_list}), size: {DEFAULT_TEXT_SIZE})",
    ]
    if files.global_macros:
        lines.append(f'#import "{files.global_macros}": *')
    if files.deck_macros:
        lines.append(f'#import "{files.deck_macros}": *')
    if files.deck_style:
        lines.append(f'#import "{files.deck_style}": {CARD_STYLE_FUNCTION}')
        lines.append(f"#show: {CARD_STYLE_FUNCTION}")
    return "\n".join(lines) + "\n"


def compute_preamble_hash(
    header: str,
    scale: float,
    file_contents: Mapping[str, bytes],
    font_fingerprint: str,
) -> str:
    digest = hashlib.sha256()
    digest.update(f"format:{PREAMBLE_FORMAT_VERSION}\n".encode())
    digest.update(header.encode())
    digest.update(f"scale:{scale!r}\n".encode())
    for path in sorted(file_contents):
        digest.update(f"file:{path}:{len(file_contents[path])}\n".encode())
        digest.update(file_contents[path])
    digest.update(f"fonts:{font_fingerprint}\n".encode())
    return digest.hexdigest()[:16]


def build_preamble(
    config: DeckConfig,
    files: PreambleFiles,
    file_contents: Mapping[str, bytes],
    font_fingerprint: str,
) -> Preamble:
    header = build_preamble_header(config, files)
    return Preamble(
        header=header,
        hash=compute_preamble_hash(header, config.scale, file_contents, font_fingerprint),
        scale=config.scale,
    )

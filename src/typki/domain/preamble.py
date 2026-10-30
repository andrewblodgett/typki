import hashlib
from collections.abc import Mapping
from dataclasses import dataclass

from typki.domain.deck import DeckConfig

PREAMBLE_FORMAT_VERSION = 2
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


def fit_width_rule(max_width: str) -> list[str]:
    return [
        "#show: body => context {",
        "  let natural-width = measure(body).width",
        f"  block(width: calc.min(natural-width, {max_width}), body)",
        "}",
    ]


def build_preamble_header(config: DeckConfig, files: PreambleFiles) -> str:
    font_list = ", ".join(f'"{font}"' for font in DEFAULT_FONTS)
    page_width = "auto" if config.fit_width else config.page_width
    lines = [
        f"#set page(width: {page_width}, height: auto, margin: {PAGE_MARGIN}, fill: none)",
        f"#set text(font: ({font_list}), size: {DEFAULT_TEXT_SIZE})",
    ]
    if config.fit_width:
        lines.extend(fit_width_rule(config.page_width))
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


def canonical_files(files: PreambleFiles) -> PreambleFiles:
    return PreambleFiles(
        global_macros="global-macros" if files.global_macros else None,
        deck_macros="deck-macros" if files.deck_macros else None,
        deck_style="deck-style" if files.deck_style else None,
    )


def contents_by_role(files: PreambleFiles, file_contents: Mapping[str, bytes]) -> dict[str, bytes]:
    roles = canonical_files(files)
    pairs = (
        (roles.global_macros, files.global_macros),
        (roles.deck_macros, files.deck_macros),
        (roles.deck_style, files.deck_style),
    )
    return {role: file_contents.get(path, b"") for role, path in pairs if role and path}


def build_preamble(
    config: DeckConfig,
    files: PreambleFiles,
    file_contents: Mapping[str, bytes],
    font_fingerprint: str,
) -> Preamble:
    canonical_header = build_preamble_header(config, canonical_files(files))
    return Preamble(
        header=build_preamble_header(config, files),
        hash=compute_preamble_hash(
            canonical_header, config.scale, contents_by_role(files, file_contents), font_fingerprint
        ),
        scale=config.scale,
    )

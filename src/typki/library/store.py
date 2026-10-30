import hashlib
from dataclasses import dataclass
from pathlib import Path

from typki.domain.deck import DeckConfig, resolve_deck_config
from typki.domain.preamble import Preamble, PreambleFiles, build_preamble
from typki.library.deck_config import load_deck_configs

GLOBAL_MACROS = "global/macros.typ"
DECKS_DIR = "decks"
FONTS_DIR = "fonts"
TEMPLATES_DIR = "templates"
OUTBOX_DIR = "outbox"
DECK_MACROS_FILENAME = "macros.typ"
DECK_STYLE_FILENAME = "style.typ"
FONT_SUFFIXES = {".ttf", ".otf", ".ttc", ".otc"}


@dataclass(frozen=True)
class ResolvedDeck:
    config: DeckConfig
    preamble: Preamble


class Library:
    def __init__(self, root: Path) -> None:
        self.root = root

    @property
    def fonts_dir(self) -> Path:
        return self.root / FONTS_DIR

    def ensure_layout(self) -> None:
        for relative in ("global", DECKS_DIR, FONTS_DIR, TEMPLATES_DIR, OUTBOX_DIR):
            (self.root / relative).mkdir(parents=True, exist_ok=True)
        global_macros = self.root / GLOBAL_MACROS
        if not global_macros.exists():
            global_macros.write_text("")

    def deck_configs(self) -> tuple[dict[str, DeckConfig], list[str]]:
        return load_deck_configs(self.root / DECKS_DIR)

    def resolve_deck(self, deck_name: str) -> ResolvedDeck:
        configs, _ = self.deck_configs()
        config = resolve_deck_config(deck_name, configs)
        files = self.preamble_files(config)
        contents = {path: (self.root / path.lstrip("/")).read_bytes() for path in files.paths()}
        preamble = build_preamble(config, files, contents, self.font_fingerprint())
        return ResolvedDeck(config=config, preamble=preamble)

    def preamble_files(self, config: DeckConfig) -> PreambleFiles:
        def typst_path_if_exists(relative: str) -> str | None:
            return f"/{relative}" if (self.root / relative).is_file() else None

        deck_prefix = f"{DECKS_DIR}/{config.folder}" if config.folder else None
        return PreambleFiles(
            global_macros=typst_path_if_exists(GLOBAL_MACROS),
            deck_macros=typst_path_if_exists(f"{deck_prefix}/{DECK_MACROS_FILENAME}")
            if deck_prefix
            else None,
            deck_style=typst_path_if_exists(f"{deck_prefix}/{DECK_STYLE_FILENAME}") if deck_prefix else None,
        )

    def font_fingerprint(self) -> str:
        if not self.fonts_dir.is_dir():
            return ""
        digest = hashlib.sha256()
        for font_path in sorted(self.fonts_dir.rglob("*")):
            if font_path.suffix.lower() in FONT_SUFFIXES and font_path.is_file():
                digest.update(font_path.relative_to(self.fonts_dir).as_posix().encode())
                digest.update(hashlib.sha256(font_path.read_bytes()).digest())
        return digest.hexdigest()[:16]

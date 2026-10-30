import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

from typki.domain.deck import DeckConfig, deck_slug, resolve_deck_config
from typki.domain.preamble import Preamble, PreambleFiles, build_preamble
from typki.library.deck_config import (
    DECK_CONFIG_FILENAME,
    deck_config_values,
    load_deck_configs,
    update_toml_keys,
)

GLOBAL_MACROS = "global/macros.typ"
DECKS_DIR = "decks"
FONTS_DIR = "fonts"
TEMPLATES_DIR = "templates"
OUTBOX_DIR = "outbox"
DECK_MACROS_FILENAME = "macros.typ"
DECK_STYLE_FILENAME = "style.typ"
FONT_SUFFIXES = {".ttf", ".otf", ".ttc", ".otc"}
STARTER_STYLE = """#let card-style(body) = {
  set text(size: 11pt)
  body
}
"""


def write_text_atomically(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-")
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(temporary_name, path)


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

    def global_macros_path(self) -> Path:
        return self.root / GLOBAL_MACROS

    def deck_folder_path(self, folder: str) -> Path:
        return self.root / DECKS_DIR / folder

    def deck_file_path(self, folder: str, filename: str) -> Path:
        return self.deck_folder_path(folder) / filename

    def read_text(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""

    def write_text(self, path: Path, text: str) -> None:
        write_text_atomically(path, text)

    def unique_folder_name(self, deck_name: str) -> str:
        base = deck_slug(deck_name)
        candidate = base
        counter = 2
        while self.deck_folder_path(candidate).exists():
            candidate = f"{base}-{counter}"
            counter += 1
        return candidate

    def create_deck_folder(self, deck_name: str) -> DeckConfig:
        inherited = self.resolve_deck(deck_name).config
        folder = self.unique_folder_name(deck_name)
        target = self.deck_folder_path(folder)
        target.mkdir(parents=True)
        for filename, starter in ((DECK_MACROS_FILENAME, ""), (DECK_STYLE_FILENAME, STARTER_STYLE)):
            source = self.deck_file_path(inherited.folder, filename) if inherited.folder else None
            if source is not None and source.is_file():
                shutil.copyfile(source, target / filename)
            else:
                write_text_atomically(target / filename, starter)
        config = replace(inherited, anki_deck=deck_name, folder=folder)
        self.write_deck_settings(config)
        return config

    def write_deck_settings(self, config: DeckConfig) -> None:
        if config.folder is None:
            raise ValueError("deck has no folder")
        path = self.deck_file_path(config.folder, DECK_CONFIG_FILENAME)
        write_text_atomically(path, update_toml_keys(self.read_text(path), deck_config_values(config)))

    def watched_files(self) -> list[Path]:
        paths = [self.global_macros_path(), self.root / "settings.toml"]
        decks_dir = self.root / DECKS_DIR
        if decks_dir.is_dir():
            for folder in sorted(decks_dir.iterdir()):
                if folder.is_dir():
                    paths.extend(
                        folder / name
                        for name in (DECK_CONFIG_FILENAME, DECK_MACROS_FILENAME, DECK_STYLE_FILENAME)
                    )
        return [path for path in paths if path.exists()]

    def watched_directories(self) -> list[Path]:
        decks_dir = self.root / DECKS_DIR
        directories = [self.root, self.root / "global", decks_dir]
        if decks_dir.is_dir():
            directories.extend(folder for folder in sorted(decks_dir.iterdir()) if folder.is_dir())
        return [directory for directory in directories if directory.is_dir()]

import hashlib
import os
import tempfile
from pathlib import Path

from typki.domain.preamble import DEFAULT_HEADER, HEADER_FILENAME, Preamble, build_preamble

FONTS_DIR = "fonts"
SETTINGS_FILENAME = "settings.toml"
FONT_SUFFIXES = {".ttf", ".otf", ".ttc", ".otc"}


def write_text_atomically(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-")
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(temporary_name, path)


class Library:
    def __init__(self, root: Path) -> None:
        self.root = root

    @property
    def fonts_dir(self) -> Path:
        return self.root / FONTS_DIR

    @property
    def header_path(self) -> Path:
        return self.root / HEADER_FILENAME

    def ensure_layout(self) -> None:
        self.fonts_dir.mkdir(parents=True, exist_ok=True)
        if not self.header_path.exists():
            write_text_atomically(self.header_path, DEFAULT_HEADER)

    def read_header(self) -> str:
        try:
            return self.header_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""

    def write_header(self, text: str) -> None:
        write_text_atomically(self.header_path, text)

    def preamble(self) -> Preamble:
        return build_preamble(self.read_header(), self.font_fingerprint())

    def font_fingerprint(self) -> str:
        if not self.fonts_dir.is_dir():
            return ""
        digest = hashlib.sha256()
        for font_path in sorted(self.fonts_dir.rglob("*")):
            if font_path.suffix.lower() in FONT_SUFFIXES and font_path.is_file():
                digest.update(font_path.relative_to(self.fonts_dir).as_posix().encode())
                digest.update(hashlib.sha256(font_path.read_bytes()).digest())
        return digest.hexdigest()[:16]

    def watched_paths(self) -> list[Path]:
        candidates = [self.root, self.header_path, self.root / SETTINGS_FILENAME]
        return [path for path in candidates if path.exists()]

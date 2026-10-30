import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

Severity = Literal["error", "warning"]

IN_MEMORY_MAIN_SUFFIX = "__typst_py_bytes__.typ"
PREAMBLE_FILE_LABEL = "preamble"
BLOCK_START = re.compile(r"^(error|warning): (.*)$")
LOCATION = re.compile(r"┌─ (.+):(\d+):(\d+)\s*$")
HINT = re.compile(r"^\s*= hint: (.*)$")


@dataclass(frozen=True)
class Diagnostic:
    severity: Severity
    message: str
    hints: tuple[str, ...] = ()
    file: str | None = None
    line: int | None = None
    column: int | None = None

    @property
    def in_card(self) -> bool:
        return self.file is None and self.line is not None

    def describe(self) -> str:
        if self.line is None:
            location = self.file or ""
        else:
            location = f"{self.file or 'card'}:{self.line}:{self.column}"
        prefix = f"{location}: " if location else ""
        return f"{prefix}{self.severity}: {self.message}"


def relative_location(raw_path: str, library_root: Path) -> str:
    candidate = Path(raw_path)
    try:
        return candidate.resolve().relative_to(library_root.resolve()).as_posix()
    except ValueError:
        return raw_path


@dataclass
class RawBlock:
    severity: Severity
    message: str
    hints: list[str] = field(default_factory=list)
    path: str | None = None
    line: int | None = None
    column: int | None = None


def parse_diagnostics(
    text: str,
    fallback_message: str,
    severity: Severity,
    header_line_count: int,
    library_root: Path,
) -> list[Diagnostic]:
    blocks: list[RawBlock] = []
    for line in text.splitlines():
        start = BLOCK_START.match(line)
        if start:
            block_severity: Severity = "warning" if start.group(1) == "warning" else "error"
            blocks.append(RawBlock(block_severity, start.group(2)))
            continue
        if not blocks:
            continue
        current = blocks[-1]
        location = LOCATION.search(line)
        if location and current.path is None:
            current.path = location.group(1)
            current.line = int(location.group(2))
            current.column = int(location.group(3)) + 1
            continue
        hint = HINT.match(line)
        if hint:
            current.hints.append(hint.group(1))
    if not blocks:
        return [Diagnostic(severity=severity, message=fallback_message)]
    return [to_diagnostic(block, header_line_count, library_root) for block in blocks]


def to_diagnostic(block: RawBlock, header_line_count: int, library_root: Path) -> Diagnostic:
    hints = tuple(block.hints)
    if block.path is None or block.line is None:
        return Diagnostic(block.severity, block.message, hints)
    if block.path.endswith(IN_MEMORY_MAIN_SUFFIX):
        card_line = block.line - header_line_count
        if card_line < 1:
            return Diagnostic(
                block.severity, block.message, hints, PREAMBLE_FILE_LABEL, block.line, block.column
            )
        return Diagnostic(block.severity, block.message, hints, None, card_line, block.column)
    return Diagnostic(
        block.severity,
        block.message,
        hints,
        relative_location(block.path, library_root),
        block.line,
        block.column,
    )

import threading
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path

import typst

from typki.domain.preamble import Preamble
from typki.render.diagnostics import Diagnostic, parse_diagnostics
from typki.render.plain_text import plain_text_from_source
from typki.render.svg_postprocess import postprocess_svg

RENDER_PIPELINE_VERSION = 2


@dataclass(frozen=True)
class SideRender:
    svg: str | None
    diagnostics: tuple[Diagnostic, ...]
    plain_text: str

    @property
    def ok(self) -> bool:
        return self.svg is not None

    @property
    def byte_size(self) -> int:
        return len(self.svg.encode()) if self.svg else 0

    @property
    def errors(self) -> tuple[Diagnostic, ...]:
        return tuple(d for d in self.diagnostics if d.severity == "error")


def current_renderer_version() -> str:
    return f"typst-py-{version('typst')}+typki-{RENDER_PIPELINE_VERSION}"


class Renderer:
    def __init__(
        self,
        library_root: Path,
        font_dirs: list[Path],
        package_cache: Path | None = None,
    ) -> None:
        self.library_root = library_root
        self.renderer_version = current_renderer_version()
        self._lock = threading.Lock()
        fonts = typst.Fonts(
            include_system_fonts=False,
            include_embedded_fonts=True,
            font_paths=[str(path) for path in font_dirs if path.is_dir()],
        )
        self._compiler = typst.Compiler(
            root=str(library_root),
            font_paths=fonts,
            ignore_system_fonts=True,
            package_cache_path=str(package_cache) if package_cache else None,
        )

    def render_side(self, source: str, preamble: Preamble) -> SideRender:
        plain_text = plain_text_from_source(source)
        main_source = preamble.wrap(source).encode()
        try:
            with self._lock:
                output, warnings = self._compiler.compile_with_warnings(input=main_source, format="svg")
        except typst.TypstError as error:
            diagnostics = parse_diagnostics(
                error.diagnostic or "",
                error.message or str(error),
                "error",
                preamble.line_count,
                self.library_root,
            )
            return SideRender(svg=None, diagnostics=tuple(diagnostics), plain_text=plain_text)
        warning_diagnostics = [
            diagnostic
            for warning in warnings
            for diagnostic in parse_diagnostics(
                warning.diagnostic or "",
                warning.message or str(warning),
                "warning",
                preamble.line_count,
                self.library_root,
            )
        ]
        svg_bytes = first_page(output)
        return SideRender(
            svg=postprocess_svg(svg_bytes, plain_text, preamble.scale),
            diagnostics=tuple(warning_diagnostics),
            plain_text=plain_text,
        )


def first_page(output: bytes | list[bytes] | None) -> bytes:
    if isinstance(output, list):
        return output[0] if output else b""
    return output or b""

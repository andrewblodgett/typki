import argparse
import sys
from contextlib import ExitStack
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths
from PySide6.QtWidgets import QApplication, QMessageBox

from typki.anki.ankiconnect import DEFAULT_URL, AnkiConnectGateway
from typki.anki.fake_anki import running_fake_ankiconnect
from typki.card_service import CardService
from typki.library.store import Library
from typki.render.compiler import Renderer
from typki.typst_syntax.catalog import warm_catalog_in_background
from typki.ui.main_window import MainWindow
from typki.ui.shortcuts import load_shortcuts
from typki.ui.theme import apply_to_application, find_theme

APP_NAME = "typki"
LIBRARY_SETTING = "library_path"
ANKI_SEEN_SETTING = "anki_connected_once"
THEME_SETTING = "theme"
DEFAULT_LIBRARY = Path.home() / "typki-library"


def parse_arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="typki", description="Write Anki flashcards in Typst.")
    parser.add_argument("--library", type=Path, help="library folder (remembered for next time)")
    parser.add_argument("--anki-url", default=DEFAULT_URL, help="AnkiConnect URL")
    parser.add_argument("--fake-anki", action="store_true", help="use an in-memory Anki for trying Typki out")
    return parser.parse_args(argv)


def resolve_library_path(settings: QSettings, requested: Path | None) -> Path:
    if requested is not None:
        path = requested.expanduser().resolve()
        settings.setValue(LIBRARY_SETTING, str(path))
        return path
    stored = settings.value(LIBRARY_SETTING)
    if isinstance(stored, str) and stored:
        return Path(stored)
    settings.setValue(LIBRARY_SETTING, str(DEFAULT_LIBRARY))
    return DEFAULT_LIBRARY


def main(argv: list[str] | None = None) -> int:
    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    settings = QSettings()
    theme = find_theme(settings.value(THEME_SETTING))
    apply_to_application(app, theme)
    warm_catalog_in_background()

    library = Library(resolve_library_path(settings, arguments.library))
    try:
        library.ensure_layout()
    except OSError as error:
        QMessageBox.critical(None, "Typki", f"Cannot use library folder {library.root}: {error}")
        return 1

    with ExitStack() as stack:
        anki_url = arguments.anki_url
        if arguments.fake_anki:
            anki_url, _ = stack.enter_context(running_fake_ankiconnect())
        gateway = AnkiConnectGateway(anki_url)
        renderer = Renderer(library.root, [library.fonts_dir])
        service = CardService(gateway, library, renderer)
        state_dir = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
        shortcuts, shortcut_problems = load_shortcuts(library.root)
        first_run = not arguments.fake_anki and not settings.value(ANKI_SEEN_SETTING, False, bool)
        window = MainWindow(
            gateway, service, state_dir, shortcuts, shortcut_problems, show_setup=first_run, theme=theme
        )
        window.theme_changed.connect(lambda name: settings.setValue(THEME_SETTING, name))
        window.connected.connect(lambda: settings.setValue(ANKI_SEEN_SETTING, True))
        window.capture.restore(window.draft_store.load())
        window.show()
        return app.exec()

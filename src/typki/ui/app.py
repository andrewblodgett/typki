import argparse
import sys
from contextlib import ExitStack
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths
from PySide6.QtWidgets import QApplication, QMessageBox

from typki.anki.ankiconnect import DEFAULT_URL, AnkiConnectGateway
from typki.anki.fake_anki import running_fake_ankiconnect
from typki.card_service import CardService
from typki.library.drafts import DraftStore
from typki.library.outbox import Outbox
from typki.library.store import Library
from typki.render.compiler import Renderer
from typki.ui.background import TaskRunner
from typki.ui.browser import BrowserPage
from typki.ui.capture import CapturePage
from typki.ui.global_page import GlobalPage
from typki.ui.main_window import MainWindow
from typki.ui.save_queue import SaveQueue
from typki.ui.shortcuts import load_shortcuts

APP_NAME = "typki"
LIBRARY_SETTING = "library_path"
DEFAULT_LIBRARY = Path.home() / "typki-library"
DRAFT_FILENAME = "draft.json"
OUTBOX_DIRNAME = "outbox"


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
        draft_store = DraftStore(state_dir / DRAFT_FILENAME)
        outbox = Outbox(state_dir / OUTBOX_DIRNAME)

        def report_error(error: Exception) -> None:
            print(f"typki: {error}", file=sys.stderr)

        render_runner = TaskRunner(1, report_error)
        anki_runner = TaskRunner(2, report_error)
        shortcuts, shortcut_problems = load_shortcuts(library.root)

        save_queue = SaveQueue(service, anki_runner, outbox)
        capture = CapturePage(service, render_runner, save_queue, draft_store)
        browser = BrowserPage(service, anki_runner)
        global_page = GlobalPage(service, render_runner)
        window = MainWindow(
            gateway,
            service,
            capture,
            browser,
            global_page,
            save_queue,
            anki_runner,
            render_runner,
            shortcuts,
            shortcut_problems,
        )
        capture.restore(draft_store.load())
        window.show()
        return app.exec()

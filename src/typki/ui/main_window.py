from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import QLabel, QMainWindow, QMessageBox, QTabWidget, QWidget

from typki.anki.gateway import AnkiGateway, AnkiUnavailableError
from typki.anki.note_type import NoteTypeHealth
from typki.card_service import CardService, NotTypkiNoteError, OpenedCard
from typki.render.diagnostics import Diagnostic
from typki.rerender.runner import Rerenderer
from typki.ui.background import TaskRunner
from typki.ui.browser import BrowserPage
from typki.ui.capture import CapturePage
from typki.ui.global_page import GlobalPage
from typki.ui.library_watcher import LibraryWatcher
from typki.ui.rerender_dialog import RerenderDialog
from typki.ui.shortcuts import SHORTCUT_ACTIONS

RECONNECT_INTERVAL_MS = 5000
STATUS_TIMEOUT_MS = 6000
CAPTURE_TAB = 0
BROWSE_TAB = 1
GLOBAL_TAB = 2


@dataclass(frozen=True)
class AnkiStartupState:
    version: int
    health: NoteTypeHealth
    created_note_type: bool
    deck_names: list[str]


def check_anki(gateway: AnkiGateway, service: CardService) -> AnkiStartupState:
    version = gateway.version()
    health = service.check_note_type()
    created = False
    if not health.exists:
        service.create_note_type()
        health = service.check_note_type()
        created = True
    return AnkiStartupState(version, health, created, gateway.deck_names())


class MainWindow(QMainWindow):
    def __init__(
        self,
        gateway: AnkiGateway,
        service: CardService,
        capture: CapturePage,
        browser: BrowserPage,
        global_page: GlobalPage,
        anki_runner: TaskRunner,
        render_runner: TaskRunner,
        shortcuts: dict[str, str],
        startup_problems: list[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.gateway = gateway
        self.service = service
        self.capture = capture
        self.browser = browser
        self.global_page = global_page
        self.rerenderer = Rerenderer(service)
        self.anki_runner = anki_runner
        self.render_runner = render_runner
        anki_runner.setParent(self)
        render_runner.setParent(self)
        self.anki_connected = False
        self.setWindowTitle("Typki")
        self.resize(1280, 820)

        self.tabs = QTabWidget()
        self.tabs.addTab(capture, "Capture")
        self.tabs.addTab(browser, "Browse")
        self.tabs.addTab(global_page, "Global")
        self.setCentralWidget(self.tabs)
        self.tabs.currentChanged.connect(self.on_tab_changed)

        self.connection_label = QLabel("Connecting to Anki…")
        self.statusBar().addPermanentWidget(self.connection_label)
        self.statusBar().addPermanentWidget(QLabel(str(service.library.root)))

        self.reconnect_timer = QTimer(self, singleShot=True, interval=RECONNECT_INTERVAL_MS)
        self.reconnect_timer.timeout.connect(self.connect_to_anki)

        self.watcher = LibraryWatcher(service.library, self)
        self.watcher.changed.connect(self.on_library_changed)
        global_page.status_message.connect(self.show_status)
        global_page.rerender_requested.connect(self.open_rerender)
        capture.status_message.connect(self.show_status)
        browser.status_message.connect(self.show_status)
        browser.open_requested.connect(self.open_note)
        capture.set_shortcut_hints(shortcuts)
        self.install_actions(shortcuts)

        if startup_problems:
            QTimer.singleShot(0, lambda: self.show_problems(startup_problems))
        self.connect_to_anki()

    def install_actions(self, shortcuts: dict[str, str]) -> None:
        handlers: dict[str, Callable[[], None]] = {
            "save_and_next": self.capture.save_and_next,
            "save_and_stay": self.capture.save_and_stay,
            "new_card": self.new_card,
            "focus_back": self.capture.focus_back,
            "focus_front": self.capture.focus_front,
            "focus_deck": lambda: self.focus_capture_widget(self.capture.deck_combo),
            "focus_template": lambda: self.focus_capture_widget(self.capture.template_combo),
            "focus_tags": lambda: self.focus_capture_widget(self.capture.tags_edit),
            "show_capture": self.show_capture,
            "show_browse": lambda: self.tabs.setCurrentIndex(BROWSE_TAB),
            "show_global": lambda: self.tabs.setCurrentIndex(GLOBAL_TAB),
            "search": self.focus_search,
            "toggle_dark": self.capture.toggle_dark,
            "toggle_phone": self.capture.toggle_phone,
        }
        card_menu = self.menuBar().addMenu("&Card")
        view_menu = self.menuBar().addMenu("&View")
        view_keys = {"show_capture", "show_browse", "show_global", "search", "toggle_dark", "toggle_phone"}
        reserved: set[QKeySequence] = set()
        for shortcut_action in SHORTCUT_ACTIONS:
            action = QAction(shortcut_action.label, self)
            sequence = QKeySequence(shortcuts[shortcut_action.key])
            action.setShortcut(sequence)
            action.triggered.connect(handlers[shortcut_action.key])
            (view_menu if shortcut_action.key in view_keys else card_menu).addAction(action)
            self.addAction(action)
            reserved.add(sequence)
        editors = (
            self.capture.front_editor,
            self.capture.back_editor,
            self.global_page.header_editor,
        )
        for editor in editors:
            editor.reserved_shortcuts = reserved
        card_menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        card_menu.addAction(quit_action)

    def on_tab_changed(self, index: int) -> None:
        if index == GLOBAL_TAB:
            self.global_page.set_sample(
                self.capture.front_editor.toPlainText(), self.capture.back_editor.toPlainText()
            )
            self.global_page.refresh_staleness()

    def on_library_changed(self) -> None:
        self.capture.request_render()
        self.global_page.on_library_changed()

    def open_rerender(self) -> None:
        self.global_page.flush_writes()
        dialog = RerenderDialog(self.rerenderer, self.anki_runner, self)
        dialog.open_requested.connect(lambda note_id: self.open_from_dialog(dialog, note_id))
        dialog.diagnostic_requested.connect(lambda diagnostic: self.reveal_from_dialog(dialog, diagnostic))
        dialog.finished_updating.connect(self.after_rerender)
        dialog.open()

    def open_from_dialog(self, dialog: RerenderDialog, note_id: int) -> None:
        dialog.accept()
        self.open_note(note_id)

    def reveal_from_dialog(self, dialog: RerenderDialog, diagnostic: Diagnostic) -> None:
        dialog.accept()
        self.tabs.setCurrentIndex(GLOBAL_TAB)
        self.global_page.reveal_diagnostic(diagnostic)

    def after_rerender(self) -> None:
        self.global_page.refresh_staleness()

    def show_capture(self) -> None:
        self.tabs.setCurrentIndex(CAPTURE_TAB)
        self.capture.focus_front()

    def focus_capture_widget(self, widget: QWidget) -> None:
        self.tabs.setCurrentIndex(CAPTURE_TAB)
        widget.setFocus()

    def new_card(self) -> None:
        self.tabs.setCurrentIndex(CAPTURE_TAB)
        self.capture.new_card()

    def focus_search(self) -> None:
        self.tabs.setCurrentIndex(BROWSE_TAB)
        self.browser.focus_search()

    def show_status(self, message: str) -> None:
        self.statusBar().showMessage(message, STATUS_TIMEOUT_MS)

    def show_problems(self, problems: list[str]) -> None:
        QMessageBox.warning(self, "Library problems", "\n".join(problems))

    def connect_to_anki(self) -> None:
        self.anki_runner.run(
            lambda: check_anki(self.gateway, self.service),
            self.on_anki_ready,
            self.on_anki_unavailable,
        )

    def on_anki_ready(self, state: AnkiStartupState) -> None:
        self.anki_connected = True
        self.connection_label.setText(f"Anki connected (AnkiConnect v{state.version})")
        self.capture.set_deck_names(state.deck_names)
        if self.tabs.currentIndex() == GLOBAL_TAB:
            self.global_page.refresh_staleness()
        if state.created_note_type:
            self.show_status("Created the 'Typki Card' note type in Anki.")
        if not state.health.healthy:
            self.offer_note_type_repair(state.health)

    def on_anki_unavailable(self, error: Exception) -> None:
        self.anki_connected = False
        if isinstance(error, AnkiUnavailableError):
            self.connection_label.setText("Anki not reachable, retrying…")
        else:
            self.connection_label.setText(f"Anki error: {error}")
        self.reconnect_timer.start()

    def offer_note_type_repair(self, health: NoteTypeHealth) -> None:
        answer = QMessageBox.question(
            self,
            "Repair note type?",
            health.describe() + "\n\nRepair it now? Existing notes and review history are kept.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.anki_runner.run(
                lambda: self.service.repair_note_type(health),
                lambda _result: self.show_status("Repaired the 'Typki Card' note type."),
                self.on_repair_failed,
            )

    def on_repair_failed(self, error: Exception) -> None:
        QMessageBox.warning(self, "Repair failed", str(error))

    def open_note(self, note_id: int) -> None:
        if self.capture.has_unsaved_new_card():
            answer = QMessageBox.question(
                self,
                "Discard card?",
                "The card in the capture form has not been saved. Discard it and open this note?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Discard:
                return
        self.show_status(f"Opening note {note_id}…")
        self.anki_runner.run(lambda: self.service.open(note_id), self.on_note_opened, self.on_open_failed)

    def on_note_opened(self, opened: OpenedCard) -> None:
        if opened.drifted:
            answer = QMessageBox.warning(
                self,
                "Card changed outside Typki",
                "The rendered fields stored in Anki differ from a fresh render of this card's source, "
                "probably because it was edited in Anki. Saving will replace them with Typki's render.",
                QMessageBox.StandardButton.Open | QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Open:
                return
        self.capture.load_opened_card(opened)
        self.tabs.setCurrentIndex(CAPTURE_TAB)

    def on_open_failed(self, error: Exception) -> None:
        if isinstance(error, NotTypkiNoteError):
            QMessageBox.information(self, "Read-only note", str(error))
        else:
            QMessageBox.warning(self, "Could not open note", str(error))

    def closeEvent(self, event: QCloseEvent) -> None:
        self.capture.save_draft()
        self.global_page.flush_writes()
        self.anki_runner.wait()
        self.render_runner.wait()
        super().closeEvent(event)

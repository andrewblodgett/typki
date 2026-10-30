from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QMenu,
    QStackedWidget,
    QTabWidget,
    QToolButton,
    QWidget,
)

from typki.anki.gateway import AnkiConnectTooOldError, AnkiGateway, AnkiUnavailableError
from typki.card_service import CardService
from typki.domain.card import StoredCard
from typki.rerender.runner import Rerenderer
from typki.ui.background import TaskRunner
from typki.ui.background_rerender import BackgroundRerender
from typki.ui.browser import BrowserPage
from typki.ui.capture import CapturePage
from typki.ui.global_page import GlobalPage
from typki.ui.library_watcher import LibraryWatcher
from typki.ui.save_queue import SaveQueue
from typki.ui.setup_page import SetupPage
from typki.ui.shortcuts import SHORTCUT_ACTIONS
from typki.ui.theme import DEFAULT_THEME, THEMES, Theme, apply_to_application

RECONNECT_INTERVAL_MS = 5000
SETUP_RECONNECT_INTERVAL_MS = 1500
MINIMUM_ANKICONNECT_VERSION = 6
NOTICE_TIMEOUT_MS = 4000
CAPTURE_TAB = 0
BROWSE_TAB = 1
GLOBAL_TAB = 2
VIEW_ACTION_KEYS = {"show_capture", "show_browse", "show_global", "search", "toggle_phone"}


@dataclass(frozen=True)
class AnkiStartupState:
    deck_names: list[str]
    tags: list[str]


def check_anki(gateway: AnkiGateway, service: CardService) -> AnkiStartupState:
    if gateway.version() < MINIMUM_ANKICONNECT_VERSION:
        raise AnkiConnectTooOldError("AnkiConnect is out of date")
    health = service.check_note_type()
    if not health.healthy:
        service.repair_note_type(health)
    return AnkiStartupState(gateway.deck_names(), gateway.get_tags())


class MainWindow(QMainWindow):
    connected = Signal()
    theme_changed = Signal(str)

    def __init__(
        self,
        gateway: AnkiGateway,
        service: CardService,
        capture: CapturePage,
        browser: BrowserPage,
        global_page: GlobalPage,
        save_queue: SaveQueue,
        anki_runner: TaskRunner,
        render_runner: TaskRunner,
        shortcuts: dict[str, str],
        startup_problems: list[str],
        show_setup: bool = False,
        theme: Theme = DEFAULT_THEME,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.gateway = gateway
        self.service = service
        self.capture = capture
        self.browser = browser
        self.global_page = global_page
        self.save_queue = save_queue
        self.anki_runner = anki_runner
        self.render_runner = render_runner
        for owned in (anki_runner, render_runner, save_queue):
            owned.setParent(self)
        self.rerender = BackgroundRerender(Rerenderer(service), anki_runner, self)
        self.anki_connected = False
        self.notice = ""
        self.setWindowTitle("Typki")
        self.resize(1280, 820)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(capture, "Capture")
        self.tabs.addTab(browser, "Browse")
        self.tabs.addTab(global_page, "Global")
        self.setup_page = SetupPage()
        self.setup_page.dismissed.connect(self.dismiss_setup)
        self.pages = QStackedWidget()
        self.pages.addWidget(self.tabs)
        self.pages.addWidget(self.setup_page)
        self.offer_setup = show_setup
        self.setCentralWidget(self.pages)
        self.previous_tab = CAPTURE_TAB
        self.tabs.currentChanged.connect(self.on_tab_changed)

        self.indicator = QLabel()
        self.statusBar().addPermanentWidget(self.indicator)
        self.statusBar().setSizeGripEnabled(False)

        self.reconnect_timer = QTimer(self, singleShot=True, interval=RECONNECT_INTERVAL_MS)
        self.reconnect_timer.timeout.connect(self.connect_to_anki)
        self.notice_timer = QTimer(self, singleShot=True, interval=NOTICE_TIMEOUT_MS)
        self.notice_timer.timeout.connect(self.clear_notice)

        self.watcher = LibraryWatcher(service.library, self)
        self.watcher.changed.connect(self.on_library_changed)
        capture.save_state_changed.connect(self.update_indicator)
        save_queue.state_changed.connect(self.update_indicator)
        save_queue.went_offline.connect(self.on_went_offline)
        self.rerender.state_changed.connect(self.update_indicator)
        browser.open_requested.connect(self.open_note)
        browser.delete_requested.connect(self.delete_note)
        anki_runner.default_error = self.show_notice_for_error
        render_runner.default_error = self.show_notice_for_error
        self.install_actions(shortcuts)
        self.apply_theme(theme)

        if startup_problems:
            self.show_notice("; ".join(startup_problems))
        self.connect_to_anki()

    def install_actions(self, shortcuts: dict[str, str]) -> None:
        handlers: dict[str, Callable[[], None]] = {
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
            "toggle_phone": self.capture.toggle_phone,
        }
        self.menu = QMenu(self)
        view_actions: list[QAction] = []
        reserved: set[QKeySequence] = set()
        for shortcut_action in SHORTCUT_ACTIONS:
            action = QAction(shortcut_action.label, self)
            sequence = QKeySequence(shortcuts[shortcut_action.key])
            action.setShortcut(sequence)
            action.triggered.connect(handlers[shortcut_action.key])
            if shortcut_action.key in VIEW_ACTION_KEYS:
                view_actions.append(action)
            else:
                self.menu.addAction(action)
            self.addAction(action)
            reserved.add(sequence)
            if shortcut_action.key == "new_card":
                self.capture.save_new_button.setToolTip(
                    sequence.toString(QKeySequence.SequenceFormat.NativeText)
                )
        for editor in (self.capture.front_editor, self.capture.back_editor, self.global_page.header_editor):
            editor.reserved_shortcuts = reserved
        self.menu.addSeparator()
        self.menu.addActions(view_actions)
        self.menu.addSeparator()
        self.theme_menu = self.menu.addMenu("Theme")
        self.theme_actions = QActionGroup(self)
        for previous, theme in zip((None, *THEMES), THEMES, strict=False):
            if previous is not None and previous.dark != theme.dark:
                self.theme_menu.addSeparator()
            theme_action = self.theme_menu.addAction(theme.name)
            theme_action.setCheckable(True)
            theme_action.setData(theme.name)
            self.theme_actions.addAction(theme_action)
            theme_action.triggered.connect(lambda _checked=False, chosen=theme: self.choose_theme(chosen))
        self.menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        self.menu.addAction(quit_action)
        self.addAction(quit_action)
        self.menu_button = QToolButton()
        self.menu_button.setText("☰")
        self.menu_button.setMenu(self.menu)
        self.menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.tabs.setCornerWidget(self.menu_button, Qt.Corner.TopRightCorner)

    def choose_theme(self, theme: Theme) -> None:
        self.apply_theme(theme)
        self.theme_changed.emit(theme.name)

    def apply_theme(self, theme: Theme) -> None:
        self.theme = theme
        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_to_application(app, theme)
        for theme_action in self.theme_actions.actions():
            theme_action.setChecked(theme_action.data() == theme.name)
        self.capture.set_theme(theme)
        self.global_page.set_theme(theme)
        self.setup_page.set_theme(theme)
        if self.browser.results.count():
            self.browser.refresh()

    def on_tab_changed(self, index: int) -> None:
        if self.previous_tab == GLOBAL_TAB and index != GLOBAL_TAB:
            self.global_page.flush_writes()
            if self.anki_connected:
                self.rerender.request()
        self.previous_tab = index
        if index == BROWSE_TAB:
            self.capture.flush()
            self.browser.refresh()
        if index == GLOBAL_TAB:
            self.global_page.set_sample(
                self.capture.front_editor.toPlainText(), self.capture.back_editor.toPlainText()
            )

    def on_library_changed(self) -> None:
        self.capture.refresh_templates()
        self.capture.request_render()
        self.global_page.on_library_changed()

    @property
    def setup_visible(self) -> bool:
        return self.pages.currentWidget() is self.setup_page

    def dismiss_setup(self) -> None:
        self.pages.setCurrentWidget(self.tabs)
        self.capture.focus_front()
        self.update_indicator()

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

    def show_notice(self, message: str) -> None:
        self.notice = message
        self.notice_timer.start()
        self.update_indicator()

    def show_notice_for_error(self, error: Exception) -> None:
        self.show_notice(str(error))

    def clear_notice(self) -> None:
        self.notice = ""
        self.update_indicator()

    def update_indicator(self) -> None:
        if self.setup_visible:
            self.indicator.setText("")
            return
        parts = []
        queued = self.save_queue.outbox.count()
        if not self.anki_connected:
            parts.append(f"Offline · {queued} queued" if queued else "Offline")
        status = self.capture.save_status()
        if status:
            parts.append(status)
        if self.rerender.total:
            parts.append(f"Re-rendering {self.rerender.done}/{self.rerender.total}")
        elif self.rerender.failed:
            parts.append(f"{self.rerender.failed} cards not re-rendered")
        if self.notice:
            parts.append(self.notice)
        self.indicator.setText(" · ".join(parts))

    def connect_to_anki(self) -> None:
        self.anki_runner.run(
            lambda: check_anki(self.gateway, self.service),
            self.on_anki_ready,
            self.on_anki_unavailable,
        )

    def on_anki_ready(self, state: AnkiStartupState) -> None:
        self.anki_connected = True
        self.offer_setup = False
        self.connected.emit()
        if self.setup_visible:
            self.dismiss_setup()
        self.capture.set_deck_names(state.deck_names)
        self.capture.tags_edit.set_known_tags(state.tags)
        self.save_queue.go_online()
        self.rerender.request()
        if self.tabs.currentIndex() == BROWSE_TAB:
            self.browser.refresh()
        self.update_indicator()

    def on_anki_unavailable(self, error: Exception) -> None:
        self.anki_connected = False
        if self.offer_setup:
            self.offer_setup = False
            self.pages.setCurrentWidget(self.setup_page)
        if self.setup_visible:
            self.setup_page.show_error(error)
            self.reconnect_timer.start(SETUP_RECONNECT_INTERVAL_MS)
        else:
            if not isinstance(error, AnkiUnavailableError):
                self.show_notice(str(error))
            self.reconnect_timer.start(RECONNECT_INTERVAL_MS)
        self.update_indicator()

    def on_went_offline(self) -> None:
        self.anki_connected = False
        self.reconnect_timer.start(RECONNECT_INTERVAL_MS)
        self.update_indicator()

    def open_note(self, note_id: int) -> None:
        self.anki_runner.run(lambda: self.service.open(note_id), self.on_note_opened)

    def on_note_opened(self, card: StoredCard) -> None:
        self.capture.load_card(card)
        self.tabs.setCurrentIndex(CAPTURE_TAB)

    def delete_note(self, note_id: int) -> None:
        self.capture.discard_if_showing(note_id)
        self.anki_runner.run(lambda: self.service.delete(note_id), lambda _result: self.on_deleted(note_id))

    def on_deleted(self, note_id: int) -> None:
        self.browser.remove_note(note_id)
        self.show_notice("Deleted")

    def closeEvent(self, event: QCloseEvent) -> None:
        self.capture.flush()
        self.capture.save_draft()
        self.global_page.flush_writes()
        self.rerender.cancel.set()
        for _ in range(50):
            if self.save_queue.idle:
                break
            self.anki_runner.wait(100)
            QApplication.processEvents()
        self.anki_runner.wait()
        self.render_runner.wait()
        super().closeEvent(event)

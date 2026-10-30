from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from typki.anki.gateway import AnkiConnectTooOldError, AnkiUnavailableError, NotAnkiConnectError
from typki.ui.theme import Theme, code_font

ANKICONNECT_CODE = "2055492159"
ANKI_DOWNLOAD_URL = "https://apps.ankiweb.net"
TITLE_STYLE = "font-size: 22pt; font-weight: 600;"
STEP_STYLE = "font-size: 12pt;"
CODE_POINT_SIZE = 16

INSTALL_STEPS = (
    f'Open Anki. If you don\'t have it, get it from <a href="{ANKI_DOWNLOAD_URL}">apps.ankiweb.net</a>.',
    "In Anki, choose <b>Tools → Add-ons → Get Add-ons…</b> and enter this code:",
    "Restart Anki.",
)
UPDATE_STEPS = (
    "In Anki, choose <b>Tools → Add-ons</b>, select AnkiConnect, and click <b>Check for Updates</b>.",
    "Restart Anki.",
)


def steps_for_error(error: Exception | None) -> tuple[str, ...]:
    if isinstance(error, AnkiConnectTooOldError):
        return UPDATE_STEPS
    return INSTALL_STEPS


def status_for_error(error: Exception | None) -> str:
    if error is None or isinstance(error, AnkiUnavailableError | AnkiConnectTooOldError):
        return "Waiting for Anki…"
    if isinstance(error, NotAnkiConnectError):
        return f"{error}. Waiting for Anki…"
    return f"{error}"


class SetupPage(QWidget):
    dismissed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title = QLabel("Connect Typki to Anki")
        self.title.setStyleSheet(TITLE_STYLE)
        self.steps_box = QVBoxLayout()
        self.steps_box.setSpacing(14)
        self.code_row = self.build_code_row()
        self.status = QLabel()
        self.offline_button = QPushButton("Continue offline")
        self.offline_button.setFlat(True)
        self.offline_button.clicked.connect(self.dismissed)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self.dismissed.emit)

        column = QVBoxLayout()
        column.setSpacing(24)
        column.addWidget(self.title)
        column.addLayout(self.steps_box)
        column.addWidget(self.status)
        column.addWidget(self.offline_button, 0, Qt.AlignmentFlag.AlignLeft)
        centered = QHBoxLayout()
        centered.addStretch(1)
        centered.addLayout(column)
        centered.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addStretch(1)
        layout.addLayout(centered)
        layout.addStretch(2)
        self.shown_steps: tuple[str, ...] = ()
        self.show_error(None)

    def build_code_row(self) -> QWidget:
        code = QLabel(ANKICONNECT_CODE)
        font = code_font()
        font.setPointSize(CODE_POINT_SIZE)
        code.setFont(font)
        code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.copy_button = QPushButton("Copy")
        self.copy_button.clicked.connect(self.copy_code)
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(28, 0, 0, 0)
        row_layout.addWidget(code)
        row_layout.addWidget(self.copy_button)
        row_layout.addStretch(1)
        return row

    def copy_code(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(ANKICONNECT_CODE)
        self.copy_button.setText("Copied")

    def show_error(self, error: Exception | None) -> None:
        self.status.setText(status_for_error(error))
        steps = steps_for_error(error)
        if steps == self.shown_steps:
            return
        self.shown_steps = steps
        while self.steps_box.count():
            item = self.steps_box.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None and widget is not self.code_row:
                widget.deleteLater()
        self.code_row.setParent(None)
        for number, text in enumerate(steps, start=1):
            step = QLabel(f"{number}.&nbsp;&nbsp;{text}")
            step.setStyleSheet(STEP_STYLE)
            step.setTextFormat(Qt.TextFormat.RichText)
            step.setOpenExternalLinks(True)
            self.steps_box.addWidget(step)
            if steps is INSTALL_STEPS and number == 2:
                self.steps_box.addWidget(self.code_row)
        self.code_row.setVisible(steps is INSTALL_STEPS)

    def set_theme(self, theme: Theme) -> None:
        self.status.setStyleSheet(f"color: {theme.muted};")

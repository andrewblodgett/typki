from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QWidget

from typki.render.diagnostics import Diagnostic
from typki.ui.theme import DEFAULT_THEME, Theme

ENTRY_ROLE = Qt.ItemDataRole.UserRole

Entry = tuple[str, Diagnostic, object]


class DiagnosticsList(QListWidget):
    revealed = Signal(object)

    def __init__(self, maximum_height: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.theme = DEFAULT_THEME
        self.maximum_height = maximum_height
        self.setObjectName("diagnostics")
        self.setVisible(False)
        self.itemActivated.connect(self.reveal)
        self.itemClicked.connect(self.reveal)

    def show_entries(self, entries: Sequence[Entry]) -> None:
        self.clear()
        for label, diagnostic, target in entries:
            item = QListWidgetItem(label)
            item.setData(ENTRY_ROLE, (diagnostic, target))
            if diagnostic.hints:
                item.setToolTip("\n".join(diagnostic.hints))
            self.addItem(item)
        self.recolor()
        self.setVisible(bool(entries))
        rows_height = sum(self.sizeHintForRow(index) for index in range(self.count()))
        self.setFixedHeight(min(rows_height + 2 * self.frameWidth(), self.maximum_height))

    def set_theme(self, theme: Theme) -> None:
        self.theme = theme
        self.recolor()

    def recolor(self) -> None:
        for index in range(self.count()):
            item = self.item(index)
            diagnostic, _target = item.data(ENTRY_ROLE)
            color = self.theme.error if diagnostic.severity == "error" else self.theme.warning
            item.setForeground(QColor(color))

    def reveal(self, item: QListWidgetItem) -> None:
        self.revealed.emit(item.data(ENTRY_ROLE)[1])

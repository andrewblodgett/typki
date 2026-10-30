from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from typki.card_service import CardRender, CardService
from typki.render.diagnostics import HEADER_FILE_LABEL, Diagnostic
from typki.ui.background import TaskRunner
from typki.ui.editor import TypstEditor
from typki.ui.preview import CardPreview

WRITE_DEBOUNCE_MS = 250
DIAGNOSTIC_ROLE = Qt.ItemDataRole.UserRole

SAMPLE_FRONT = "*Define* a compact set $K subset RR$."
SAMPLE_BACK = """$K$ is *compact* if every open cover of $K$ has a finite subcover:
$ K subset.eq union.big_(i in I) U_i ==> K subset.eq U_(i_1) union dots.c union U_(i_n) $"""


class GlobalPage(QWidget):
    def __init__(
        self,
        service: CardService,
        render_runner: TaskRunner,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.render_runner = render_runner
        self.sample_front = SAMPLE_FRONT
        self.sample_back = SAMPLE_BACK
        self.loading = False
        self.write_pending = False
        self.render_in_flight = False
        self.render_pending = False

        self.header_editor = TypstEditor()
        self.diagnostics_list = QListWidget()
        self.diagnostics_list.setMaximumHeight(100)
        self.diagnostics_list.setVisible(False)
        self.preview = CardPreview()

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.header_editor, 1)
        left_layout.addWidget(self.diagnostics_list)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(self.preview)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        layout = QVBoxLayout(self)
        layout.addWidget(splitter, 1)

        self.write_timer = QTimer(self, singleShot=True, interval=WRITE_DEBOUNCE_MS)
        self.write_timer.timeout.connect(self.flush_writes)
        self.header_editor.textChanged.connect(self.on_header_edited)
        self.diagnostics_list.itemActivated.connect(self.on_diagnostic_activated)
        self.diagnostics_list.itemClicked.connect(self.on_diagnostic_activated)

        self.reload_from_disk()

    def set_sample(self, front: str, back: str) -> None:
        if front.strip() or back.strip():
            self.sample_front, self.sample_back = front, back
        else:
            self.sample_front, self.sample_back = SAMPLE_FRONT, SAMPLE_BACK
        self.request_render()

    def reload_from_disk(self) -> None:
        text = self.service.library.read_header()
        if self.header_editor.toPlainText() != text:
            self.loading = True
            self.header_editor.setPlainText(text)
            self.loading = False
        self.request_render()

    def on_header_edited(self) -> None:
        if self.loading:
            return
        self.write_pending = True
        self.write_timer.start()

    def flush_writes(self) -> None:
        if not self.write_pending:
            return
        self.write_pending = False
        self.service.library.write_header(self.header_editor.toPlainText())
        self.request_render()

    def on_library_changed(self) -> None:
        if self.write_pending:
            return
        focused = QApplication.focusWidget()
        if self.isActiveWindow() and focused is self.header_editor:
            self.request_render()
        else:
            self.reload_from_disk()

    def request_render(self) -> None:
        if self.render_in_flight:
            self.render_pending = True
            return
        self.render_in_flight = True
        front, back = self.sample_front, self.sample_back
        self.render_runner.run(
            lambda: self.service.render(front, back), self.on_rendered, self.on_render_crashed
        )

    def finish_render_cycle(self) -> bool:
        self.render_in_flight = False
        if self.render_pending:
            self.render_pending = False
            self.request_render()
            return False
        return True

    def on_rendered(self, card_render: CardRender) -> None:
        if not self.finish_render_cycle():
            return
        self.preview.set_side("front", card_render.front.svg, not card_render.front.ok)
        self.preview.set_side("back", card_render.back.svg, not card_render.back.ok)
        diagnostics = list(card_render.front.diagnostics)
        diagnostics += [d for d in card_render.back.diagnostics if d not in diagnostics]
        self.show_diagnostics(diagnostics)

    def on_render_crashed(self, error: Exception) -> None:
        if self.finish_render_cycle():
            self.show_diagnostics([Diagnostic("error", str(error))])

    def show_diagnostics(self, diagnostics: list[Diagnostic]) -> None:
        self.diagnostics_list.clear()
        header_diagnostics = [d for d in diagnostics if d.file == HEADER_FILE_LABEL]
        self.header_editor.show_diagnostics(
            [Diagnostic(d.severity, d.message, d.hints, None, d.line, d.column) for d in header_diagnostics]
        )
        for diagnostic in diagnostics:
            item = QListWidgetItem(diagnostic.describe())
            item.setData(DIAGNOSTIC_ROLE, diagnostic)
            if diagnostic.hints:
                item.setToolTip("\n".join(diagnostic.hints))
            color = Qt.GlobalColor.red if diagnostic.severity == "error" else Qt.GlobalColor.darkYellow
            item.setForeground(color)
            self.diagnostics_list.addItem(item)
        self.diagnostics_list.setVisible(bool(diagnostics))

    def on_diagnostic_activated(self, item: QListWidgetItem) -> None:
        self.reveal_diagnostic(item.data(DIAGNOSTIC_ROLE))

    def reveal_diagnostic(self, diagnostic: Diagnostic) -> None:
        if diagnostic.file == HEADER_FILE_LABEL and diagnostic.line is not None:
            self.header_editor.jump_to(diagnostic.line, diagnostic.column or 1)

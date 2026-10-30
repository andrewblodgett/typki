from collections.abc import Callable

from PySide6.QtWidgets import QApplication, QWidget

from typki.card_service import CardRender, CardService
from typki.render.diagnostics import HEADER_FILE_LABEL, Diagnostic
from typki.ui.background import CoalescingTask, TaskRunner, debouncer
from typki.ui.editor import TypstEditor
from typki.ui.editor_field import EditorField
from typki.ui.layout import page, splitter
from typki.ui.preview import CardPreview
from typki.ui.theme import Theme

WRITE_DEBOUNCE_MS = 250

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
        self.sample_front = SAMPLE_FRONT
        self.sample_back = SAMPLE_BACK
        self.loading = False
        self.write_pending = False

        self.header_editor = TypstEditor()
        self.header_field = EditorField("Header", self.header_editor)
        self.preview = CardPreview()
        page(self, (splitter(self.header_field, self.preview), 1))

        self.render_task = CoalescingTask(
            render_runner, self.render_job, self.on_rendered, self.on_render_crashed
        )
        self.write_timer = debouncer(self, WRITE_DEBOUNCE_MS, self.flush_writes)
        self.header_editor.textChanged.connect(self.on_header_edited)
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
        if self.isActiveWindow() and QApplication.focusWidget() is self.header_editor:
            self.request_render()
        else:
            self.reload_from_disk()

    def request_render(self) -> None:
        self.render_task.request()

    def render_job(self) -> Callable[[], CardRender]:
        front, back = self.sample_front, self.sample_back
        return lambda: self.service.render(front, back)

    def on_rendered(self, card_render: CardRender) -> None:
        self.preview.set_side("front", card_render.front.svg, not card_render.front.ok)
        self.preview.set_side("back", card_render.back.svg, not card_render.back.ok)
        diagnostics = list(card_render.front.diagnostics)
        diagnostics += [d for d in card_render.back.diagnostics if d not in diagnostics]
        self.show_diagnostics(diagnostics)

    def on_render_crashed(self, error: Exception) -> None:
        self.header_field.show_problem(str(error))

    def show_diagnostics(self, diagnostics: list[Diagnostic]) -> None:
        header_diagnostics = [
            Diagnostic(d.severity, d.message, d.hints, None, d.line, d.column)
            for d in diagnostics
            if d.file == HEADER_FILE_LABEL
        ]
        unplaced = [d for d in diagnostics if d.file is None and d.line is None]
        self.header_field.show_diagnostics(header_diagnostics + unplaced)

    def set_theme(self, theme: Theme) -> None:
        for themed in (self.header_field, self.preview):
            themed.set_theme(theme)

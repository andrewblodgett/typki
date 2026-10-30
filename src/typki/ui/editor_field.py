from PySide6.QtCore import Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from typki.render.diagnostics import Diagnostic
from typki.ui.editor import TypstEditor
from typki.ui.layout import caption_row, filled
from typki.ui.theme import Theme

FIELD_SPACING = 4
MESSAGE_HEIGHT = 22


def field_text(diagnostic: Diagnostic) -> str:
    if diagnostic.in_card:
        return f"Line {diagnostic.line}: {diagnostic.message}"
    if diagnostic.file and diagnostic.line is not None:
        return f"{diagnostic.file} line {diagnostic.line}: {diagnostic.message}"
    return diagnostic.message


class MessageLine(QLabel):
    pressed = Signal()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.pressed.emit()
        super().mousePressEvent(event)


class EditorField(QWidget):
    def __init__(self, caption: str, editor: TypstEditor, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.editor = editor
        self.jump_target: Diagnostic | None = None
        self.message = MessageLine()
        self.message.setObjectName("message")
        self.message.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.message.setFixedHeight(MESSAGE_HEIGHT)
        self.message.pressed.connect(self.jump_to_message)
        filled(QVBoxLayout(self), [caption_row(caption), (editor, 1), self.message], spacing=FIELD_SPACING)

    def show_diagnostics(self, diagnostics: list[Diagnostic]) -> None:
        self.editor.show_diagnostics(diagnostics)
        ordered = sorted(diagnostics, key=lambda diagnostic: diagnostic.severity != "error")
        if not ordered:
            self.show_message("", "")
            return
        first = ordered[0]
        more = f"   +{len(ordered) - 1} more" if len(ordered) > 1 else ""
        details = [field_text(d) + "".join(f"\n  hint: {hint}" for hint in d.hints) for d in ordered]
        self.show_message(field_text(first) + more, first.severity, "\n".join(details))
        self.jump_target = first if first.in_card else None

    def show_problem(self, text: str) -> None:
        self.show_message(text, "error")
        self.jump_target = None

    def show_message(self, text: str, level: str, details: str = "") -> None:
        self.message.setText(text)
        self.message.setToolTip(details or text)
        self.message.setProperty("level", level)
        self.message.style().polish(self.message)

    def jump_to_message(self) -> None:
        target = self.jump_target
        if target is not None and target.line is not None:
            self.editor.jump_to(target.line, target.column or 1)

    def set_theme(self, theme: Theme) -> None:
        self.editor.set_theme(theme)

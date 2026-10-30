import zlib
from collections.abc import Callable

from PySide6.QtCore import QEvent, QModelIndex, QObject, QPersistentModelIndex, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QKeyEvent,
    QKeySequence,
    QPainter,
    QPalette,
    QStandardItem,
    QStandardItemModel,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
)
from PySide6.QtWidgets import (
    QCompleter,
    QListView,
    QPlainTextEdit,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTextEdit,
    QWidget,
)

from typki.domain.template import PLACEHOLDER_PATTERN, placeholder_spans
from typki.render.diagnostics import Diagnostic
from typki.typst_syntax import editing
from typki.typst_syntax.catalog import typst_catalog
from typki.typst_syntax.completion import CompletionResult, complete
from typki.typst_syntax.editing import Edit
from typki.typst_syntax.lexer import SPAN_KINDS, Kind, lex
from typki.ui.text_positions import TextPositions
from typki.ui.theme import DEFAULT_THEME, Theme, code_font

INDENT = editing.INDENT
BRACKETS = {"(": ")", "[": "]", "{": "}"}
CLOSING_BRACKETS = {closer: opener for opener, closer in BRACKETS.items()}
BRACKET_SCAN_LIMIT = 20_000
AUTOCLOSE_CHARACTERS = frozenset('()[]{}$"*_')
COMPLETION_TRIGGER_CHARACTERS = frozenset("#.")
DETAIL_ROLE = Qt.ItemDataRole.UserRole + 2
COMPLETION_POPUP_WIDTH = 360
COMPLETION_VISIBLE_ITEMS = 10
GLYPH_LENGTH = 2
POPUP_KEYS = frozenset(
    {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape, Qt.Key.Key_Tab, Qt.Key.Key_Backtab}
)
TEXT_MODIFIERS = (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ShiftModifier)


def char_format(
    color: str | None, bold: bool = False, italic: bool = False, underline: bool = False
) -> QTextCharFormat:
    text_format = QTextCharFormat()
    if color is not None:
        text_format.setForeground(QColor(color))
    if bold:
        text_format.setFontWeight(QFont.Weight.Bold)
    if italic:
        text_format.setFontItalic(True)
    if underline:
        text_format.setFontUnderline(True)
    return text_format


def kind_formats_for(theme: Theme) -> dict[Kind, QTextCharFormat]:
    return {
        Kind.COMMENT: char_format(theme.comment, italic=True),
        Kind.KEYWORD: char_format(theme.keyword),
        Kind.FUNCTION: char_format(theme.function),
        Kind.VARIABLE: char_format(theme.function),
        Kind.STRING: char_format(theme.string),
        Kind.RAW: char_format(theme.string),
        Kind.NUMBER: char_format(theme.number),
        Kind.LABEL: char_format(theme.number),
        Kind.REFERENCE: char_format(theme.number),
        Kind.ESCAPE: char_format(theme.keyword),
        Kind.LINK: char_format(theme.function, underline=True),
        Kind.SHORTHAND: char_format(theme.keyword),
        Kind.LIST_MARKER: char_format(theme.keyword, bold=True),
        Kind.DELIMITER: char_format(theme.comment),
        Kind.HEADING: char_format(theme.heading, bold=True),
        Kind.STRONG: char_format(None, bold=True),
        Kind.EMPH: char_format(None, italic=True),
        Kind.MATH_DELIMITER: char_format(theme.math, bold=True),
        Kind.MATH_TEXT: char_format(theme.math),
        Kind.MATH_SYMBOL: char_format(theme.heading),
        Kind.MATH_OPERATOR: char_format(theme.keyword),
    }


def placeholder_format_for(theme: Theme) -> QTextCharFormat:
    text_format = QTextCharFormat()
    background = QColor(theme.warning)
    background.setAlpha(48)
    text_format.setBackground(background)
    text_format.setForeground(QColor(theme.warning))
    return text_format


Span = tuple[int, int, QTextCharFormat]


class TypstHighlighter(QSyntaxHighlighter):
    def __init__(self, document: QTextDocument) -> None:
        super().__init__(document)
        self.cached_text: str | None = None
        self.cached_positions = TextPositions("")
        self.cached_spans: list[Span] = []
        self.set_theme(DEFAULT_THEME)

    def set_theme(self, theme: Theme) -> None:
        self.kind_formats = kind_formats_for(theme)
        self.placeholder_format = placeholder_format_for(theme)
        self.cached_text = None
        self.rehighlight()

    def document_spans(self) -> list[Span]:
        text = self.document().toPlainText()
        if text == self.cached_text:
            return self.cached_spans
        positions = TextPositions(text)
        tokens = lex(text).tokens
        span_tokens = [token for token in tokens if token.kind in SPAN_KINDS]
        spans: list[Span] = [
            (positions.to_qt(token.start), positions.to_qt(token.end), self.kind_formats[token.kind])
            for token in span_tokens
        ]
        for token in tokens:
            if token.kind in SPAN_KINDS:
                continue
            token_format = QTextCharFormat(self.kind_formats[token.kind])
            for span in span_tokens:
                if span.start <= token.start < span.end:
                    token_format.merge(self.kind_formats[span.kind])
                    token_format.merge(self.kind_formats[token.kind])
            spans.append((positions.to_qt(token.start), positions.to_qt(token.end), token_format))
        self.cached_text = text
        self.cached_positions = positions
        self.cached_spans = spans
        return spans

    def highlightBlock(self, text: str) -> None:
        spans = self.document_spans()
        block = self.currentBlock()
        block_start = block.position()
        block_end = block_start + max(block.length() - 1, 0)
        for start, end, token_format in spans:
            if end <= block_start or start >= block_end:
                continue
            clipped_start = max(start, block_start)
            self.setFormat(clipped_start - block_start, min(end, block_end) - clipped_start, token_format)
        block_positions = TextPositions(text)
        for match in PLACEHOLDER_PATTERN.finditer(text):
            start = block_positions.to_qt(match.start())
            self.setFormat(start, block_positions.to_qt(match.end()) - start, self.placeholder_format)
        prefix = (self.cached_text or "")[: self.cached_positions.from_qt(block_end)]
        self.setCurrentBlockState(zlib.crc32(prefix.encode()) & 0x3FFFFFFF)


class CompletionDelegate(QStyledItemDelegate):
    def paint(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> None:
        super().paint(painter, option, index)
        detail = index.data(DETAIL_ROLE)
        if not detail:
            return
        painter.save()
        role = (
            QPalette.ColorRole.Text
            if len(str(detail)) <= GLYPH_LENGTH
            else QPalette.ColorRole.PlaceholderText
        )
        painter.setPen(option.palette.color(role))
        detail_rect = option.rect.adjusted(0, 0, -12, 0)
        alignment = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        painter.drawText(detail_rect, alignment, str(detail))
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex) -> QSize:
        size = super().sizeHint(option, index)
        return QSize(
            size.width() + option.fontMetrics.horizontalAdvance(str(index.data(DETAIL_ROLE) or "")) + 32,
            size.height(),
        )


class CompletionPopup(QObject):
    def __init__(self, editor: TypstEditor) -> None:
        super().__init__(editor)
        self.editor = editor
        self.model = QStandardItemModel(self)
        self.completer = QCompleter(self.model, editor)
        self.completer.setWidget(editor)
        self.completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self.completer.setMaxVisibleItems(COMPLETION_VISIBLE_ITEMS)
        view = QListView()
        view.setObjectName("completions")
        view.setUniformItemSizes(True)
        view.setFont(code_font())
        self.completer.setPopup(view)
        view.setItemDelegate(CompletionDelegate(view))
        self.completer.activated.connect(self.on_activated)

    @property
    def view(self) -> QListView:
        popup = self.completer.popup()
        assert isinstance(popup, QListView)
        return popup

    def is_visible(self) -> bool:
        return self.view.isVisible()

    def hide(self) -> None:
        self.view.hide()

    def show_result(self, result: CompletionResult | None) -> None:
        if result is None or not result.items:
            self.hide()
            return
        self.model.clear()
        for completion in result.items:
            item = QStandardItem(completion.label)
            item.setData(completion.detail, DETAIL_ROLE)
            self.model.appendRow(item)
        self.completer.setCompletionPrefix("")
        rect = self.editor.cursorRect()
        rect.setWidth(COMPLETION_POPUP_WIDTH)
        self.completer.complete(rect)
        self.view.setCurrentIndex(self.completer.completionModel().index(0, 0))

    def on_activated(self, label: str) -> None:
        self.hide()
        self.editor.accept_completion(label)


class TypstEditor(QPlainTextEdit):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFont(code_font())
        self.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self.setTabChangesFocus(False)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.highlighter = TypstHighlighter(self.document())
        self.reserved_shortcuts: set[QKeySequence] = set()
        self.theme = DEFAULT_THEME
        self.definitions_source: Callable[[], str] = self.toPlainText
        self.diagnostic_selections: list[QTextEdit.ExtraSelection] = []
        self.bracket_selections: list[QTextEdit.ExtraSelection] = []
        self.completion_popup = CompletionPopup(self)
        self.key_handlers: dict[str, Callable[[], None]] = {
            key_name(sequence): handler
            for sequence, handler in (
                ("Ctrl+/", self.toggle_comment),
                ("Ctrl+Shift+K", self.delete_lines),
                ("Ctrl+L", self.select_lines),
                ("Alt+Up", lambda: self.move_lines(upward=True)),
                ("Alt+Down", lambda: self.move_lines(upward=False)),
                ("Alt+Shift+Up", lambda: self.duplicate_lines(upward=True)),
                ("Alt+Shift+Down", lambda: self.duplicate_lines(upward=False)),
                ("Ctrl+]", self.indent_lines),
                ("Ctrl+[", self.outdent_lines),
                ("Ctrl+Shift+Return", self.insert_line_above),
                ("Ctrl+Space", lambda: self.update_completion(explicit=True)),
                ("Ctrl+Y", self.redo),
                ("Home", lambda: self.smart_home(extend=False)),
                ("Shift+Home", lambda: self.smart_home(extend=True)),
            )
        }
        self.cursorPositionChanged.connect(self.highlight_matching_brackets)

    def set_theme(self, theme: Theme) -> None:
        self.theme = theme
        was_blocked = self.blockSignals(True)
        self.highlighter.set_theme(theme)
        self.blockSignals(was_blocked)
        self.highlight_matching_brackets()

    def set_source(self, text: str) -> None:
        self.setPlainText(text)
        self.select_placeholder(forward=True, from_position=0)

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.ShortcutOverride and isinstance(event, QKeyEvent):
            sequence = QKeySequence(event.keyCombination())
            if sequence in self.reserved_shortcuts:
                event.ignore()
                return True
            if key_name(sequence) in self.key_handlers:
                event.accept()
                return True
        return super().event(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if self.completion_popup.is_visible() and key in POPUP_KEYS:
            event.ignore()
            return
        handler = self.key_handlers.get(key_name(QKeySequence(event.keyCombination())))
        if handler is not None:
            self.completion_popup.hide()
            handler()
            return
        if self.handle_editing_key(event):
            self.after_text_key(event)
            return
        super().keyPressEvent(event)
        self.after_text_key(event)

    def handle_editing_key(self, event: QKeyEvent) -> bool:
        key = event.key()
        modifiers = event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        text, start, end = self.text_and_selection()
        if key == Qt.Key.Key_Tab and modifiers == Qt.KeyboardModifier.NoModifier:
            if "\n" in text[start:end]:
                self.apply_edit(editing.indent_lines(text, start, end))
            elif not self.select_placeholder(forward=True):
                self.insertPlainText(INDENT)
            return True
        if key == Qt.Key.Key_Backtab:
            if not self.select_placeholder(forward=False):
                self.apply_edit(editing.outdent_lines(text, start, end))
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and modifiers in TEXT_MODIFIERS:
            self.apply_edit(editing.insert_newline(text, start, end))
            return True
        if key == Qt.Key.Key_Backspace and modifiers == Qt.KeyboardModifier.NoModifier:
            edit = editing.delete_backward(text, start, end)
            if edit is None:
                return False
            self.apply_edit(edit)
            return True
        typed = event.text()
        if len(typed) == 1 and typed in AUTOCLOSE_CHARACTERS and modifiers in TEXT_MODIFIERS:
            edit = editing.type_character(text, start, end, typed, lex(text).mode_at(start))
            if edit is None:
                return False
            self.apply_edit(edit)
            return True
        return False

    def after_text_key(self, event: QKeyEvent) -> None:
        typed = event.text()
        modifiers = event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        is_word = len(typed) == 1 and (typed.isalnum() or typed in "_-")
        is_deletion = event.key() in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete)
        refreshes = is_deletion and self.completion_popup.is_visible()
        typing = modifiers in TEXT_MODIFIERS
        if typing and (is_word or typed in COMPLETION_TRIGGER_CHARACTERS or refreshes):
            self.update_completion(explicit=False)
        else:
            self.completion_popup.hide()

    def text_and_selection(self) -> tuple[str, int, int]:
        text = self.toPlainText()
        positions = TextPositions(text)
        cursor = self.textCursor()
        return text, positions.from_qt(cursor.selectionStart()), positions.from_qt(cursor.selectionEnd())

    def text_and_anchor(self) -> tuple[str, int, int]:
        text = self.toPlainText()
        positions = TextPositions(text)
        cursor = self.textCursor()
        return text, positions.from_qt(cursor.anchor()), positions.from_qt(cursor.position())

    def select_range(self, anchor: int, position: int) -> None:
        positions = TextPositions(self.toPlainText())
        cursor = self.textCursor()
        cursor.setPosition(positions.to_qt(anchor))
        cursor.setPosition(positions.to_qt(position), QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cursor)

    def replace_range(self, start: int, end: int, replacement: str) -> None:
        positions = TextPositions(self.toPlainText())
        cursor = self.textCursor()
        cursor.beginEditBlock()
        cursor.setPosition(positions.to_qt(start))
        cursor.setPosition(positions.to_qt(end), QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(replacement)
        cursor.endEditBlock()

    def update_completion(self, explicit: bool) -> None:
        text, start, end = self.text_and_selection()
        if start != end:
            self.completion_popup.hide()
            return
        result = complete(text, end, typst_catalog(), self.definitions_source(), explicit)
        self.completion_popup.show_result(result)

    def accept_completion(self, label: str) -> None:
        text, start, end = self.text_and_selection()
        if start != end:
            return
        result = complete(text, end, typst_catalog(), self.definitions_source(), explicit=True)
        completion = next((item for item in result.items if item.label == label), None) if result else None
        if result is None or completion is None:
            return
        self.replace_range(result.replace_start, result.replace_end, completion.insert)
        target = result.replace_start + completion.cursor_offset
        self.select_range(target, target)

    def apply_edit(self, edit: Edit) -> None:
        if edit.start != edit.end or edit.replacement:
            self.replace_range(edit.start, edit.end, edit.replacement)
        self.select_range(edit.selection_start, edit.selection_end)

    def selection_edit(self, operation: Callable[[str, int, int], Edit | None]) -> None:
        edit = operation(*self.text_and_selection())
        if edit is not None:
            self.apply_edit(edit)

    def toggle_comment(self) -> None:
        self.selection_edit(editing.toggle_line_comment)

    def delete_lines(self) -> None:
        self.selection_edit(editing.delete_lines)

    def indent_lines(self) -> None:
        self.selection_edit(editing.indent_lines)

    def outdent_lines(self) -> None:
        self.selection_edit(editing.outdent_lines)

    def move_lines(self, upward: bool) -> None:
        self.selection_edit(lambda text, start, end: editing.move_lines(text, start, end, upward))

    def duplicate_lines(self, upward: bool) -> None:
        self.selection_edit(lambda text, start, end: editing.duplicate_lines(text, start, end, upward))

    def insert_line_above(self) -> None:
        text, _anchor, position = self.text_and_anchor()
        self.apply_edit(editing.insert_line_above(text, position))

    def select_lines(self) -> None:
        text, start, end = self.text_and_selection()
        self.select_range(*editing.select_lines(text, start, end))

    def smart_home(self, extend: bool) -> None:
        text, anchor, position = self.text_and_anchor()
        target = editing.smart_home(text, position)
        self.select_range(anchor if extend else target, target)

    def select_placeholder(self, forward: bool, from_position: int | None = None) -> bool:
        text, start, end = self.text_and_selection()
        spans = placeholder_spans(text)
        if not spans:
            return False
        cursor_anchor = end if forward else start
        anchor = cursor_anchor if from_position is None else from_position
        if forward:
            candidates = [span for span in spans if span[0] >= anchor] or spans
            span_start, span_end = candidates[0]
        else:
            candidates = [span for span in spans if span[1] <= anchor] or spans
            span_start, span_end = candidates[-1]
        self.select_range(span_start, span_end)
        return True

    def highlight_matching_brackets(self) -> None:
        self.bracket_selections = []
        text, start, end = self.text_and_selection()
        pair = matching_bracket_pair(text, end) if start == end else None
        if pair is not None:
            positions = TextPositions(text)
            background = QColor(self.theme.accent)
            background.setAlpha(70)
            for index in pair:
                bracket_cursor = self.textCursor()
                bracket_cursor.setPosition(positions.to_qt(index))
                bracket_cursor.setPosition(positions.to_qt(index + 1), QTextCursor.MoveMode.KeepAnchor)
                selection = QTextEdit.ExtraSelection()
                selection.cursor = bracket_cursor
                selection.format.setBackground(background)
                self.bracket_selections.append(selection)
        self.refresh_extra_selections()

    def refresh_extra_selections(self) -> None:
        self.setExtraSelections(self.diagnostic_selections + self.bracket_selections)

    def show_diagnostics(self, diagnostics: list[Diagnostic]) -> None:
        selections = []
        for diagnostic in diagnostics:
            if not diagnostic.in_card or diagnostic.line is None:
                continue
            cursor = self.cursor_at(diagnostic.line, diagnostic.column or 1)
            cursor.movePosition(QTextCursor.MoveOperation.EndOfWord, QTextCursor.MoveMode.KeepAnchor)
            if not cursor.hasSelection():
                cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
            selection = QTextEdit.ExtraSelection()
            selection.cursor = cursor
            selection.format.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
            color = self.theme.error if diagnostic.severity == "error" else self.theme.warning
            selection.format.setUnderlineColor(QColor(color))
            selection.format.setProperty(QTextFormat.Property.FullWidthSelection, False)
            selections.append(selection)
        self.diagnostic_selections = selections
        self.refresh_extra_selections()

    def cursor_at(self, line: int, column: int) -> QTextCursor:
        block = self.document().findBlockByNumber(max(line - 1, 0))
        block_text = block.text()
        offset = TextPositions(block_text).to_qt(min(max(column - 1, 0), len(block_text)))
        cursor = QTextCursor(block)
        cursor.setPosition(block.position() + offset)
        return cursor

    def jump_to(self, line: int, column: int) -> None:
        self.setTextCursor(self.cursor_at(line, column))
        self.setFocus()


def key_name(sequence: QKeySequence | str) -> str:
    return (sequence if isinstance(sequence, QKeySequence) else QKeySequence(sequence)).toString()


def matching_bracket_pair(text: str, position: int) -> tuple[int, int] | None:
    for candidate in (position - 1, position):
        if 0 <= candidate < len(text) and (
            text[candidate] in BRACKETS or text[candidate] in CLOSING_BRACKETS
        ):
            match = find_matching_bracket(text, candidate)
            if match is not None:
                return candidate, match
    return None


def find_matching_bracket(text: str, position: int) -> int | None:
    character = text[position]
    if character in BRACKETS:
        target, step, limit = BRACKETS[character], 1, min(len(text), position + BRACKET_SCAN_LIMIT)
    else:
        target, step, limit = CLOSING_BRACKETS[character], -1, max(-1, position - BRACKET_SCAN_LIMIT)
    depth = 0
    index = position
    while index != limit:
        current = text[index]
        if current == character:
            depth += 1
        elif current == target:
            depth -= 1
            if depth == 0:
                return index
        index += step
    return None

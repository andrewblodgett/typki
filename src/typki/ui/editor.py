import zlib

from pygments.lexers import TypstLexer
from pygments.token import Token, _TokenType
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QKeyEvent,
    QKeySequence,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
)
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit, QWidget

from typki.domain.template import PLACEHOLDER_PATTERN, placeholder_spans
from typki.render.diagnostics import Diagnostic

INDENT = "  "
MATH_DELIMITER = "$"


def char_format(color: str | None, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    text_format = QTextCharFormat()
    if color is not None:
        text_format.setForeground(QColor(color))
    if bold:
        text_format.setFontWeight(QFont.Weight.Bold)
    text_format.setFontItalic(italic)
    return text_format


TOKEN_FORMATS: dict[_TokenType, QTextCharFormat] = {
    Token.Comment: char_format("#8a8a8a", italic=True),
    Token.Keyword: char_format("#a03fbf", bold=True),
    Token.Name.Function: char_format("#2b6fd6"),
    Token.Name.Label: char_format("#c26a00"),
    Token.Literal.String: char_format("#2e8b3e"),
    Token.Literal.Number: char_format("#c26a00"),
    Token.Generic.Heading: char_format("#2b6fd6", bold=True),
    Token.Generic.Strong: char_format(None, bold=True),
    Token.Generic.Emph: char_format(None, italic=True),
}
MATH_FORMAT = char_format("#0f7f8c")
MATH_DELIMITER_FORMAT = char_format("#0f7f8c", bold=True)


def placeholder_format() -> QTextCharFormat:
    text_format = QTextCharFormat()
    text_format.setBackground(QColor("#fff1b8"))
    text_format.setForeground(QColor("#7a5b00"))
    return text_format


PLACEHOLDER_FORMAT = placeholder_format()


def format_for_token(token_type: _TokenType) -> QTextCharFormat | None:
    current: _TokenType | None = token_type
    while current is not None:
        if current in TOKEN_FORMATS:
            return TOKEN_FORMATS[current]
        current = current.parent
    return None


class TypstHighlighter(QSyntaxHighlighter):
    def __init__(self, document: QTextDocument) -> None:
        super().__init__(document)
        self.lexer = TypstLexer(stripnl=False, ensurenl=False)
        self.cached_text: str | None = None
        self.cached_spans: list[tuple[int, int, QTextCharFormat]] = []

    def document_spans(self) -> list[tuple[int, int, QTextCharFormat]]:
        text = self.document().toPlainText()
        if text == self.cached_text:
            return self.cached_spans
        spans: list[tuple[int, int, QTextCharFormat]] = []
        position = 0
        in_math = False
        for token_type, value in self.lexer.get_tokens(text):
            if token_type in Token.Punctuation and value == MATH_DELIMITER:
                in_math = not in_math
                spans.append((position, len(value), MATH_DELIMITER_FORMAT))
            else:
                token_format = format_for_token(token_type)
                if token_format is None and in_math and token_type not in Token.Text.Whitespace:
                    token_format = MATH_FORMAT
                if token_format is not None:
                    spans.append((position, len(value), token_format))
            position += len(value)
        self.cached_text = text
        self.cached_spans = spans
        return spans

    def highlightBlock(self, text: str) -> None:
        block_start = self.currentBlock().position()
        block_end = block_start + len(text)
        for start, length, token_format in self.document_spans():
            end = start + length
            if end <= block_start or start >= block_end:
                continue
            clipped_start = max(start, block_start)
            self.setFormat(clipped_start - block_start, min(end, block_end) - clipped_start, token_format)
        for match in PLACEHOLDER_PATTERN.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), PLACEHOLDER_FORMAT)
        prefix = self.document().toPlainText()[:block_end]
        self.setCurrentBlockState(zlib.crc32(prefix.encode()) & 0x3FFFFFFF)


class TypstEditor(QPlainTextEdit):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setPointSizeF(max(font.pointSizeF(), 11.0))
        self.setFont(font)
        self.setTabChangesFocus(False)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.highlighter = TypstHighlighter(self.document())
        self.reserved_shortcuts: set[QKeySequence] = set()

    def set_source(self, text: str) -> None:
        self.setPlainText(text)
        self.select_placeholder(forward=True, from_position=0)

    def event(self, event: QEvent) -> bool:
        if (
            event.type() == QEvent.Type.ShortcutOverride
            and isinstance(event, QKeyEvent)
            and QKeySequence(event.keyCombination()) in self.reserved_shortcuts
        ):
            event.ignore()
            return True
        return super().event(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Tab and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            if not self.select_placeholder(forward=True):
                self.insertPlainText(INDENT)
            return
        if event.key() == Qt.Key.Key_Backtab:
            self.select_placeholder(forward=False)
            return
        super().keyPressEvent(event)

    def select_placeholder(self, forward: bool, from_position: int | None = None) -> bool:
        spans = placeholder_spans(self.toPlainText())
        if not spans:
            return False
        cursor = self.textCursor()
        if from_position is not None:
            anchor = from_position
        elif forward:
            anchor = cursor.selectionEnd()
        else:
            anchor = cursor.selectionStart()
        if forward:
            candidates = [span for span in spans if span[0] >= anchor] or spans
            start, end = candidates[0]
        else:
            candidates = [span for span in spans if span[1] <= anchor] or spans
            start, end = candidates[-1]
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cursor)
        return True

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
            color = "#d0342c" if diagnostic.severity == "error" else "#c58b00"
            selection.format.setUnderlineColor(QColor(color))
            selection.format.setProperty(QTextFormat.Property.FullWidthSelection, False)
            selections.append(selection)
        self.setExtraSelections(selections)

    def cursor_at(self, line: int, column: int) -> QTextCursor:
        block = self.document().findBlockByNumber(max(line - 1, 0))
        cursor = QTextCursor(block)
        offset = min(max(column - 1, 0), max(block.length() - 1, 0))
        cursor.setPosition(block.position() + offset)
        return cursor

    def jump_to(self, line: int, column: int) -> None:
        self.setTextCursor(self.cursor_at(line, column))
        self.setFocus()

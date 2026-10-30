import zlib

from pygments.lexers import TypstLexer
from pygments.token import Token, _TokenType
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
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
from typki.ui.theme import DEFAULT_THEME, Theme, code_font

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


TokenFormats = dict[_TokenType, QTextCharFormat]


def token_formats_for(theme: Theme) -> TokenFormats:
    return {
        Token.Comment: char_format(theme.comment, italic=True),
        Token.Keyword: char_format(theme.keyword, bold=True),
        Token.Name.Function: char_format(theme.function),
        Token.Name.Label: char_format(theme.number),
        Token.Literal.String: char_format(theme.string),
        Token.Literal.Number: char_format(theme.number),
        Token.Generic.Heading: char_format(theme.heading, bold=True),
        Token.Generic.Strong: char_format(None, bold=True),
        Token.Generic.Emph: char_format(None, italic=True),
    }


def placeholder_format_for(theme: Theme) -> QTextCharFormat:
    text_format = QTextCharFormat()
    background = QColor(theme.warning)
    background.setAlpha(48)
    text_format.setBackground(background)
    text_format.setForeground(QColor(theme.warning))
    return text_format


def format_for_token(token_type: _TokenType, token_formats: TokenFormats) -> QTextCharFormat | None:
    current: _TokenType | None = token_type
    while current is not None:
        if current in token_formats:
            return token_formats[current]
        current = current.parent
    return None


class TypstHighlighter(QSyntaxHighlighter):
    def __init__(self, document: QTextDocument) -> None:
        super().__init__(document)
        self.lexer = TypstLexer(stripnl=False, ensurenl=False)
        self.cached_text: str | None = None
        self.cached_spans: list[tuple[int, int, QTextCharFormat]] = []
        self.set_theme(DEFAULT_THEME)

    def set_theme(self, theme: Theme) -> None:
        self.token_formats = token_formats_for(theme)
        self.math_format = char_format(theme.math)
        self.math_delimiter_format = char_format(theme.math, bold=True)
        self.placeholder_format = placeholder_format_for(theme)
        self.cached_text = None
        self.rehighlight()

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
                spans.append((position, len(value), self.math_delimiter_format))
            else:
                token_format = format_for_token(token_type, self.token_formats)
                if token_format is None and in_math and token_type not in Token.Text.Whitespace:
                    token_format = self.math_format
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
            self.setFormat(match.start(), match.end() - match.start(), self.placeholder_format)
        prefix = self.document().toPlainText()[:block_end]
        self.setCurrentBlockState(zlib.crc32(prefix.encode()) & 0x3FFFFFFF)


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

    def set_theme(self, theme: Theme) -> None:
        self.theme = theme
        was_blocked = self.blockSignals(True)
        self.highlighter.set_theme(theme)
        self.blockSignals(was_blocked)

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
            color = self.theme.error if diagnostic.severity == "error" else self.theme.warning
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

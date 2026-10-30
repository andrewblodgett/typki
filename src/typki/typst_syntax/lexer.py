import re
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache


class Mode(StrEnum):
    MARKUP = "markup"
    MATH = "math"
    CODE = "code"


class Kind(StrEnum):
    COMMENT = "comment"
    KEYWORD = "keyword"
    FUNCTION = "function"
    VARIABLE = "variable"
    STRING = "string"
    NUMBER = "number"
    LABEL = "label"
    REFERENCE = "reference"
    ESCAPE = "escape"
    RAW = "raw"
    LINK = "link"
    SHORTHAND = "shorthand"
    LIST_MARKER = "list_marker"
    DELIMITER = "delimiter"
    HEADING = "heading"
    STRONG = "strong"
    EMPH = "emph"
    MATH_DELIMITER = "math_delimiter"
    MATH_TEXT = "math_text"
    MATH_SYMBOL = "math_symbol"
    MATH_OPERATOR = "math_operator"


SPAN_KINDS = frozenset({Kind.HEADING, Kind.STRONG, Kind.EMPH})


@dataclass(frozen=True)
class Token:
    start: int
    end: int
    kind: Kind


@dataclass(frozen=True)
class Region:
    start: int
    end: int
    mode: Mode


@dataclass(frozen=True)
class Lexed:
    tokens: tuple[Token, ...]
    regions: tuple[Region, ...]

    def mode_at(self, position: int) -> Mode:
        mode = Mode.MARKUP
        best_start = -1
        for region in self.regions:
            if region.start <= position <= region.end and region.start >= best_start:
                best_start = region.start
                mode = region.mode
        return mode


DECLARATION_KEYWORDS = frozenset({"let", "set", "show", "import", "include", "context"})
CONTROL_KEYWORDS = frozenset({"if", "for", "while", "return", "break", "continue"})
STATEMENT_KEYWORDS = DECLARATION_KEYWORDS | CONTROL_KEYWORDS
KEYWORDS = STATEMENT_KEYWORDS | {"else", "in", "as", "not", "and", "or", "none", "auto", "true", "false"}
CODE_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")
MATH_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:\.[A-Za-z][A-Za-z0-9]*)*")
NUMBER = re.compile(r"(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?(?:pt|mm|cm|in|em|fr|deg|rad|%)?")
MATH_NUMBER = re.compile(r"\d+(?:\.\d+)?")
LABEL = re.compile(r"<[A-Za-z_][A-Za-z0-9_:.\-]*>")
REFERENCE = re.compile(r"@[A-Za-z_][A-Za-z0-9_:.\-]*[A-Za-z0-9_]")
URL = re.compile(r"https?://[^\s<>\[\]()\"]+[^\s<>\[\]()\".,;:!?]")
HEADING = re.compile(r"=+(?=\s)")
LIST_MARKER = re.compile(r"(?:[-+]|\d+\.)(?=\s)")
ESCAPE = re.compile(r"\\(?:u\{[0-9A-Fa-f]*\}|.|\n)")
MARKUP_SHORTHAND = re.compile(r"---|--|\.\.\.|~|-\?")
MATH_OPERATOR = re.compile(r"<==>|<=>|==>|<==|-->|<--|->|<-|=>|<=|>=|!=|:=|::=|\.\.\.|\|\||[\^_/&']")
CLOSER_FOR = {"(": ")", "[": "]", "{": "}"}


def is_word_character(character: str) -> bool:
    return character.isalnum()


class Lexer:
    def __init__(self, text: str) -> None:
        self.text = text
        self.length = len(text)
        self.position = 0
        self.tokens: list[Token] = []
        self.regions: list[Region] = []

    def run(self) -> Lexed:
        self.markup(None)
        return Lexed(tuple(self.tokens), tuple(self.regions))

    def peek(self, offset: int = 0) -> str:
        index = self.position + offset
        return self.text[index] if 0 <= index < self.length else ""

    def emit(self, start: int, end: int, kind: Kind) -> None:
        if end > start:
            self.tokens.append(Token(start, end, kind))

    def emit_match(self, pattern: re.Pattern[str], kind: Kind) -> bool:
        match = pattern.match(self.text, self.position)
        if match is None or match.end() == self.position:
            return False
        self.emit(self.position, match.end(), kind)
        self.position = match.end()
        return True

    def at_line_start(self) -> bool:
        index = self.position - 1
        while index >= 0 and self.text[index] in " \t":
            index -= 1
        return index < 0 or self.text[index] == "\n"

    def comment(self) -> bool:
        if self.text.startswith("//", self.position):
            end = self.text.find("\n", self.position)
            end = self.length if end < 0 else end
            self.emit(self.position, end, Kind.COMMENT)
            self.position = end
            return True
        if self.text.startswith("/*", self.position):
            depth = 0
            index = self.position
            while index < self.length:
                if self.text.startswith("/*", index):
                    depth += 1
                    index += 2
                elif self.text.startswith("*/", index):
                    depth -= 1
                    index += 2
                    if depth == 0:
                        break
                else:
                    index += 1
            self.emit(self.position, index, Kind.COMMENT)
            self.position = index
            return True
        return False

    def string(self) -> None:
        start = self.position
        self.position += 1
        while self.position < self.length:
            character = self.text[self.position]
            if character == "\\":
                self.position += 2
                continue
            self.position += 1
            if character == '"':
                break
        self.position = min(self.position, self.length)
        self.emit(start, self.position, Kind.STRING)

    def raw(self) -> None:
        start = self.position
        fence_length = 0
        while self.peek(fence_length) == "`":
            fence_length += 1
        if fence_length == 2:
            self.position += 2
        else:
            fence = "`" * fence_length
            end = self.text.find(fence, self.position + fence_length)
            self.position = self.length if end < 0 else end + fence_length
        self.emit(start, self.position, Kind.RAW)

    def markup(self, closer: str | None) -> None:
        region_start = self.position
        bracket_depth = 0
        strong_start: int | None = None
        emph_start: int | None = None
        heading_end: int | None = None
        while self.position < self.length:
            character = self.text[self.position]
            if heading_end is not None and self.position >= heading_end:
                heading_end = None
            if character == "]" and closer == "]" and bracket_depth == 0:
                break
            if character == "\n" and self.text.startswith("\n", self.position + 1):
                self.close_span(strong_start, Kind.STRONG)
                self.close_span(emph_start, Kind.EMPH)
                strong_start = emph_start = None
            if self.comment():
                continue
            if character == "\\":
                self.emit_match(ESCAPE, Kind.ESCAPE)
                continue
            if character == "$":
                self.math()
                continue
            if character == "#":
                self.embedded()
                continue
            if character == "`":
                self.raw()
                continue
            if self.at_line_start():
                if character == "=" and HEADING.match(self.text, self.position):
                    line_end = self.text.find("\n", self.position)
                    heading_end = self.length if line_end < 0 else line_end
                    self.emit(self.position, heading_end, Kind.HEADING)
                    self.emit_match(HEADING, Kind.LIST_MARKER)
                    continue
                if self.emit_match(LIST_MARKER, Kind.LIST_MARKER):
                    continue
                if character == "/" and self.peek(1) == " ":
                    self.emit(self.position, self.position + 1, Kind.LIST_MARKER)
                    self.position += 1
                    continue
            if character in "*_" and not self.inside_word():
                kind = Kind.STRONG if character == "*" else Kind.EMPH
                self.emit(self.position, self.position + 1, Kind.DELIMITER)
                self.position += 1
                if kind == Kind.STRONG:
                    strong_start = self.toggle_span(strong_start, Kind.STRONG)
                else:
                    emph_start = self.toggle_span(emph_start, Kind.EMPH)
                continue
            if character == "<" and self.emit_match(LABEL, Kind.LABEL):
                continue
            if (
                character == "@"
                and not is_word_character(self.peek(-1))
                and self.emit_match(REFERENCE, Kind.REFERENCE)
            ):
                continue
            if character == "h" and self.emit_match(URL, Kind.LINK):
                continue
            if character in "-.~" and self.emit_match(MARKUP_SHORTHAND, Kind.SHORTHAND):
                continue
            if character == "[":
                bracket_depth += 1
            elif character == "]":
                bracket_depth -= 1
            self.position += 1
        self.close_span(strong_start, Kind.STRONG)
        self.close_span(emph_start, Kind.EMPH)
        self.regions.append(Region(region_start, self.position, Mode.MARKUP))

    def inside_word(self) -> bool:
        return is_word_character(self.peek(-1)) and is_word_character(self.peek(1))

    def toggle_span(self, span_start: int | None, kind: Kind) -> int | None:
        if span_start is None:
            return self.position
        self.emit(span_start, self.position - 1, kind)
        return None

    def close_span(self, span_start: int | None, kind: Kind) -> None:
        if span_start is not None:
            self.emit(span_start, self.position, kind)

    def math(self) -> None:
        self.emit(self.position, self.position + 1, Kind.MATH_DELIMITER)
        self.position += 1
        region_start = self.position
        while self.position < self.length:
            character = self.text[self.position]
            if character == "$":
                break
            if self.comment():
                continue
            if character == "\\":
                self.emit_match(ESCAPE, Kind.ESCAPE)
                continue
            if character == '"':
                self.string()
                continue
            if character == "#":
                self.embedded()
                continue
            if character.isalpha() and character.isascii():
                self.math_identifier()
                continue
            if character.isdigit() and self.emit_match(MATH_NUMBER, Kind.NUMBER):
                continue
            if self.emit_match(MATH_OPERATOR, Kind.MATH_OPERATOR):
                continue
            self.position += 1
        self.regions.append(Region(region_start, self.position, Mode.MATH))
        if self.position < self.length:
            self.emit(self.position, self.position + 1, Kind.MATH_DELIMITER)
            self.position += 1

    def math_identifier(self) -> None:
        match = MATH_IDENTIFIER.match(self.text, self.position)
        assert match is not None
        start, end = match.span()
        if end - start == 1:
            kind = Kind.MATH_TEXT
        elif self.text.startswith("(", end):
            kind = Kind.FUNCTION
        else:
            kind = Kind.MATH_SYMBOL
        self.emit(start, end, kind)
        self.position = end

    def embedded(self) -> None:
        start = self.position
        self.position += 1
        character = self.peek()
        region_start = self.position
        identifier = CODE_IDENTIFIER.match(self.text, self.position)
        if identifier is not None:
            name = identifier.group().rstrip("-")
            if name in STATEMENT_KEYWORDS:
                self.emit(start, self.position + len(name), Kind.KEYWORD)
                self.position += len(name)
                self.statement(name)
            elif name in KEYWORDS:
                self.emit(start, self.position + len(name), Kind.KEYWORD)
                self.position += len(name)
            else:
                self.emit(start, start + 1, self.identifier_kind(self.position + len(name)))
                self.identifier_chain()
        elif character and character in "({[":
            self.emit(start, start + 1, Kind.KEYWORD)
            self.block(character)
            self.postfix_chain()
        elif character == '"':
            self.string()
        elif character.isdigit():
            self.emit_match(NUMBER, Kind.NUMBER)
        else:
            return
        self.regions.append(Region(region_start, self.position, Mode.CODE))

    def identifier_kind(self, end: int) -> Kind:
        return Kind.FUNCTION if self.text.startswith(("(", "["), end) else Kind.VARIABLE

    def identifier_chain(self) -> None:
        while True:
            identifier = CODE_IDENTIFIER.match(self.text, self.position)
            if identifier is None:
                return
            end = self.position + len(identifier.group().rstrip("-"))
            self.emit(self.position, end, self.identifier_kind(end))
            self.position = end
            self.postfix_chain()
            if self.peek() == "." and CODE_IDENTIFIER.match(self.text, self.position + 1):
                self.position += 1
                continue
            return

    def postfix_chain(self) -> None:
        while self.peek() in ("(", "["):
            self.block(self.peek())

    def block(self, opener: str) -> None:
        self.position += 1
        if opener == "[":
            self.markup("]")
        else:
            self.code(CLOSER_FOR[opener])
        if self.peek() == CLOSER_FOR[opener]:
            self.position += 1

    def statement(self, keyword: str) -> None:
        region_start = self.position
        while self.position < self.length:
            character = self.text[self.position]
            if character in "\n;":
                break
            if character == "]":
                break
            if character in "[{":
                self.block(character)
                if not self.continues_with_else():
                    break
                continue
            if character == "(" and keyword == "set":
                self.block(character)
                if not self.text.startswith(" if", self.position):
                    break
                continue
            self.code_element()
        self.regions.append(Region(region_start, self.position, Mode.CODE))

    def continues_with_else(self) -> bool:
        rest = self.text[self.position : self.position + 64].lstrip(" \t")
        return rest.startswith("else")

    def code(self, closer: str) -> None:
        region_start = self.position
        while self.position < self.length:
            if self.text[self.position] == closer:
                break
            if self.text[self.position] in ")]}":
                break
            self.code_element()
        self.regions.append(Region(region_start, self.position, Mode.CODE))

    def code_element(self) -> None:
        character = self.text[self.position]
        if self.comment():
            return
        if character == '"':
            self.string()
            return
        if character == "$":
            self.math()
            return
        if character in "([{":
            self.block(character)
            return
        if character == "<" and self.emit_match(LABEL, Kind.LABEL):
            return
        if character.isdigit() or (character == "." and self.peek(1).isdigit()):
            self.emit_match(NUMBER, Kind.NUMBER)
            return
        identifier = CODE_IDENTIFIER.match(self.text, self.position)
        if identifier is not None:
            name = identifier.group().rstrip("-") or identifier.group()
            end = self.position + len(name)
            if name in KEYWORDS:
                self.emit(self.position, end, Kind.KEYWORD)
            else:
                self.emit(self.position, end, self.identifier_kind(end))
            self.position = end
            return
        if self.text.startswith("=>", self.position):
            self.emit(self.position, self.position + 2, Kind.KEYWORD)
            self.position += 2
            return
        self.position += 1


@lru_cache(maxsize=8)
def lex(text: str) -> Lexed:
    try:
        return Lexer(text).run()
    except RecursionError:
        return Lexed((), ())

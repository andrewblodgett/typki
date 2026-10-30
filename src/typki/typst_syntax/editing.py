from dataclasses import dataclass

from typki.typst_syntax.lexer import Mode

INDENT = "  "
COMMENT_PREFIX = "//"
PAIRS = {"(": ")", "[": "]", "{": "}", "$": "$", '"': '"'}
CLOSERS = frozenset(")]}")
SYMMETRIC = frozenset('$"')
MARKUP_WRAPPERS = {"*": "*", "_": "_"}
AUTOCLOSE_BEFORE = frozenset(" \t\n)]},;.:$")


@dataclass(frozen=True)
class Edit:
    start: int
    end: int
    replacement: str
    selection_start: int
    selection_end: int


def line_start(text: str, position: int) -> int:
    return text.rfind("\n", 0, position) + 1


def line_end(text: str, position: int) -> int:
    end = text.find("\n", position)
    return len(text) if end < 0 else end


def leading_whitespace(line: str) -> str:
    return line[: len(line) - len(line.lstrip(" \t"))]


def selected_line_range(text: str, start: int, end: int) -> tuple[int, int]:
    if end > start and end == line_start(text, end):
        end -= 1
    return line_start(text, start), line_end(text, end)


def type_character(text: str, start: int, end: int, character: str, mode: Mode) -> Edit | None:
    if start != end:
        closer = PAIRS.get(character) or (MARKUP_WRAPPERS.get(character) if mode == Mode.MARKUP else None)
        if closer is None:
            return None
        wrapped = character + text[start:end] + closer
        return Edit(start, end, wrapped, start + 1, end + 1)
    previous = text[start - 1] if start > 0 else ""
    following = text[start] if start < len(text) else ""
    if previous == "\\":
        return None
    if character in CLOSERS or character in SYMMETRIC:
        overtype = following == character and (
            character in CLOSERS
            or (character == "$" and mode == Mode.MATH)
            or (character == '"' and mode != Mode.MARKUP)
        )
        if overtype:
            return Edit(start, start, "", start + 1, start + 1)
    if character not in PAIRS:
        return None
    if following and following not in AUTOCLOSE_BEFORE:
        return None
    if character == "$" and mode == Mode.MATH:
        return None
    if character == '"' and (mode == Mode.MARKUP or previous.isalnum()):
        return None
    return Edit(start, start, character + PAIRS[character], start + 1, start + 1)


def delete_backward(text: str, start: int, end: int) -> Edit | None:
    if start != end or start == 0 or start >= len(text):
        return None
    opener = text[start - 1]
    if PAIRS.get(opener) != text[start]:
        return None
    return Edit(start - 1, start + 1, "", start - 1, start - 1)


def insert_newline(text: str, start: int, end: int) -> Edit:
    current_line = text[line_start(text, start) : start]
    indent = leading_whitespace(current_line)
    previous = text[start - 1] if start > 0 else ""
    following = text[end] if end < len(text) else ""
    if previous in "([{" and previous and following == PAIRS[previous]:
        inner = "\n" + indent + INDENT
        replacement = inner + "\n" + indent
        return Edit(start, end, replacement, start + len(inner), start + len(inner))
    if previous and previous in "([{":
        indent += INDENT
    replacement = "\n" + indent
    return Edit(start, end, replacement, start + len(replacement), start + len(replacement))


def map_position(position: int, changes: list[tuple[int, int, str]]) -> int:
    shift = 0
    for change_start, removed, inserted in changes:
        if change_start > position:
            break
        if change_start + removed <= position:
            shift += len(inserted) - removed
        else:
            shift += change_start - position
    return position + shift


def edit_lines(text: str, start: int, end: int, changes: list[tuple[int, int, str]]) -> Edit:
    first, last = selected_line_range(text, start, end)
    pieces: list[str] = []
    cursor = first
    for change_start, removed, inserted in changes:
        pieces.append(text[cursor:change_start])
        pieces.append(inserted)
        cursor = change_start + removed
    pieces.append(text[cursor:last])
    return Edit(first, last, "".join(pieces), map_position(start, changes), map_position(end, changes))


def line_starts(text: str, start: int, end: int) -> list[int]:
    first, last = selected_line_range(text, start, end)
    starts = [first]
    while True:
        newline = text.find("\n", starts[-1], last)
        if newline < 0:
            return starts
        starts.append(newline + 1)


def toggle_line_comment(text: str, start: int, end: int) -> Edit:
    starts = line_starts(text, start, end)
    lines = [(position, text[position : line_end(text, position)]) for position in starts]
    filled = [(position, line) for position, line in lines if line.strip()]
    if not filled:
        filled = lines
    commented = all(line.lstrip(" \t").startswith(COMMENT_PREFIX) for _position, line in filled)
    changes: list[tuple[int, int, str]] = []
    if commented:
        for position, line in filled:
            column = len(leading_whitespace(line))
            removed = len(COMMENT_PREFIX) + (1 if line[column + len(COMMENT_PREFIX) :].startswith(" ") else 0)
            changes.append((position + column, removed, ""))
    else:
        column = min(len(leading_whitespace(line)) for _position, line in filled)
        changes = [(position + column, 0, COMMENT_PREFIX + " ") for position, _line in filled]
    return edit_lines(text, start, end, changes)


def indent_lines(text: str, start: int, end: int) -> Edit:
    changes = [
        (position, 0, INDENT)
        for position in line_starts(text, start, end)
        if line_end(text, position) > position
    ]
    return edit_lines(text, start, end, changes)


def outdent_lines(text: str, start: int, end: int) -> Edit:
    changes: list[tuple[int, int, str]] = []
    for position in line_starts(text, start, end):
        line = text[position : line_end(text, position)]
        removable = len(line) - len(line.lstrip(" "))
        if line.startswith("\t"):
            changes.append((position, 1, ""))
        elif removable:
            changes.append((position, min(removable, len(INDENT)), ""))
    return edit_lines(text, start, end, changes)


def move_lines(text: str, start: int, end: int, upward: bool) -> Edit | None:
    first, last = selected_line_range(text, start, end)
    block = text[first:last]
    if upward:
        if first == 0:
            return None
        neighbor_start = line_start(text, first - 1)
        neighbor = text[neighbor_start : first - 1]
        shift = -(len(neighbor) + 1)
        return Edit(neighbor_start, last, block + "\n" + neighbor, start + shift, end + shift)
    if last >= len(text):
        return None
    neighbor_end = line_end(text, last + 1)
    neighbor = text[last + 1 : neighbor_end]
    shift = len(neighbor) + 1
    return Edit(first, neighbor_end, neighbor + "\n" + block, start + shift, end + shift)


def duplicate_lines(text: str, start: int, end: int, upward: bool) -> Edit:
    first, last = selected_line_range(text, start, end)
    block = text[first:last]
    shift = 0 if upward else len(block) + 1
    return Edit(first, last, block + "\n" + block, start + shift, end + shift)


def delete_lines(text: str, start: int, end: int) -> Edit:
    first, last = selected_line_range(text, start, end)
    column = start - line_start(text, start)
    if last < len(text):
        removal_start, removal_end = first, last + 1
    else:
        removal_start, removal_end = max(first - 1, 0), last
    remaining = text[:removal_start] + text[removal_end:]
    target_line = min(first, len(remaining))
    target_line = line_start(remaining, target_line)
    target = min(target_line + column, line_end(remaining, target_line))
    return Edit(removal_start, removal_end, "", target, target)


def select_lines(text: str, start: int, end: int) -> tuple[int, int]:
    first = line_start(text, start)
    last = line_end(text, end)
    return first, min(last + 1, len(text))


def smart_home(text: str, position: int) -> int:
    start = line_start(text, position)
    first_character = start + len(leading_whitespace(text[start : line_end(text, position)]))
    return start if position == first_character else first_character


def insert_line_above(text: str, position: int) -> Edit:
    start = line_start(text, position)
    indent = leading_whitespace(text[start : line_end(text, position)])
    return Edit(start, start, indent + "\n", start + len(indent), start + len(indent))

from collections.abc import Iterable
from dataclasses import dataclass

from typki.domain.template import LET_DEFINITION
from typki.typst_syntax.catalog import CATALOG_MODULES, Catalog, Entry
from typki.typst_syntax.lexer import KEYWORDS, STATEMENT_KEYWORDS, Kind, Lexed, Mode, Token, lex

CODE_PATH_CHARACTERS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.")
MATH_PATH_CHARACTERS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.")
MATH_AUTO_PREFIX_LENGTH = 2
MAXIMUM_ITEMS = 80
VALUE_KEYWORDS = frozenset({"none", "auto", "true", "false"})
LITERAL_KINDS = frozenset({Kind.STRING, Kind.COMMENT, Kind.RAW})


@dataclass(frozen=True)
class Completion:
    label: str
    insert: str
    detail: str
    kind: str
    cursor_offset: int

    @staticmethod
    def plain(label: str, detail: str, kind: str) -> Completion:
        return Completion(label, label, detail, kind, len(label))


@dataclass(frozen=True)
class CompletionResult:
    replace_start: int
    replace_end: int
    prefix: str
    items: tuple[Completion, ...]


def header_definitions(header: str) -> tuple[Completion, ...]:
    definitions: dict[str, Completion] = {}
    for match in LET_DEFINITION.finditer(header):
        _indent, name, parameters = match.groups()
        if parameters is None:
            definitions.setdefault(name, Completion.plain(name, "header", "variable"))
        else:
            detail = f"({', '.join(part.strip() for part in parameters.split(',') if part.strip())})"
            definitions.setdefault(name, Completion(name, name, detail, "function", len(name)))
    return tuple(definitions.values())


def entry_completion(entry: Entry) -> Completion:
    if entry.kind == "symbol":
        return Completion.plain(entry.name, entry.glyph, "symbol")
    if entry.callable:
        return Completion(entry.name, entry.name, entry.kind, "function", len(entry.name))
    return Completion.plain(entry.name, entry.kind, "module" if entry.kind == "module" else "variable")


def keyword_completions(statements_only: bool) -> tuple[Completion, ...]:
    return tuple(
        Completion(keyword, keyword + " ", "keyword", "keyword", len(keyword) + 1)
        if keyword in STATEMENT_KEYWORDS
        else Completion.plain(keyword, "keyword", "keyword")
        for keyword in sorted(KEYWORDS)
        if keyword in STATEMENT_KEYWORDS or keyword in VALUE_KEYWORDS or not statements_only
    )


def with_call_parentheses(completion: Completion, next_character: str) -> Completion:
    if completion.kind != "function" or next_character in ("(", "["):
        return completion
    insert = completion.insert + "()"
    return Completion(
        completion.label, insert, completion.detail, completion.kind, len(completion.insert) + 1
    )


def match_tier(label: str, prefix: str) -> int | None:
    if not prefix or label.startswith(prefix):
        return 0
    if label.lower().startswith(prefix.lower()):
        return 1
    if len(prefix) >= 2 and prefix.lower() in label.lower():
        return 2
    return None


def ranked(
    candidates: Iterable[Completion], prefix: str, preferred: frozenset[str] = frozenset()
) -> tuple[Completion, ...]:
    seen: set[str] = set()
    scored: list[tuple[int, int, int, str, Completion]] = []
    for candidate in candidates:
        if candidate.label in seen:
            continue
        tier = match_tier(candidate.label, prefix)
        if tier is None:
            continue
        seen.add(candidate.label)
        preference = 0 if candidate.label in preferred else 1
        scored.append((tier, preference, len(candidate.label), candidate.label, candidate))
    scored.sort(key=lambda item: item[:4])
    return tuple(item[4] for item in scored[:MAXIMUM_ITEMS])


def is_already_complete(items: tuple[Completion, ...], prefix: str) -> bool:
    return any(item.label == prefix for item in items) and not any(
        item.label != prefix and item.label.startswith(prefix) for item in items
    )


def path_start(text: str, position: int, allowed: frozenset[str]) -> int:
    start = position
    while start > 0 and text[start - 1] in allowed:
        start -= 1
    return start


def variant_completions(entry: Entry, typed: str) -> tuple[Completion, ...]:
    variants = (
        Completion.plain(modifiers, glyph, "symbol")
        for modifiers, glyph in entry.variants
        if modifiers.startswith(typed)
    )
    return ranked(variants, typed)


def member_completions(
    catalog: Catalog, scope: dict[str, Entry], segments: list[str], position: int, next_character: str
) -> CompletionResult | None:
    first = segments[0]
    if first in CATALOG_MODULES and first != "std":
        module = catalog.module(first)
        if len(segments) == 2:
            prefix = segments[1]
            items = tuple(
                with_call_parentheses(item, next_character)
                for item in ranked((entry_completion(entry) for entry in module.values()), prefix)
            )
            return CompletionResult(position - len(prefix), position, prefix, items)
        entry = module.get(segments[1])
        modifier_segments = segments[2:]
    else:
        entry = scope.get(first)
        modifier_segments = segments[1:]
    if entry is None or not entry.variants:
        return None
    typed = ".".join(modifier_segments)
    return CompletionResult(position - len(typed), position, typed, variant_completions(entry, typed))


def literal_is_closed(text: str, token: Token) -> bool:
    content = text[token.start : token.end]
    if token.kind == Kind.STRING:
        return len(content) >= 2 and content.endswith('"')
    if token.kind == Kind.RAW:
        return len(content) >= 2 and content.endswith("`")
    return content.startswith("/*") and content.endswith("*/") and len(content) >= 4


def inside_literal(text: str, lexed: Lexed, position: int) -> bool:
    for token in lexed.tokens:
        if token.kind not in LITERAL_KINDS or not token.start < position <= token.end:
            continue
        if position < token.end or not literal_is_closed(text, token):
            return True
    return False


def complete(
    text: str,
    position: int,
    catalog: Catalog,
    header: str = "",
    explicit: bool = False,
) -> CompletionResult | None:
    lexed = lex(text)
    if inside_literal(text, lexed, position):
        return None
    mode = lexed.mode_at(position)
    code_start = path_start(text, position, CODE_PATH_CHARACTERS)
    after_hash = code_start > 0 and text[code_start - 1] == "#"
    if after_hash or mode == Mode.CODE:
        scope_mode = Mode.CODE
        start = code_start
    elif mode == Mode.MATH:
        scope_mode = Mode.MATH
        start = path_start(text, position, MATH_PATH_CHARACTERS)
    else:
        return None
    path = text[start:position]
    if path and not (path[0].isalpha() or path[0] == "_"):
        return None
    segments = path.split(".")
    if scope_mode == Mode.MATH:
        scope = {**catalog.module("sym"), **catalog.module("math")}
    else:
        scope = catalog.module("std")
    next_character = text[position : position + 1]
    if len(segments) > 1:
        return member_completions(catalog, scope, segments, position, next_character)
    prefix = segments[0]
    if not explicit:
        if scope_mode == Mode.MATH and len(prefix) < MATH_AUTO_PREFIX_LENGTH:
            return None
        if scope_mode == Mode.CODE and not prefix and not after_hash:
            return None
    definitions = header_definitions(header)
    candidates: list[Completion] = list(definitions)
    if scope_mode == Mode.CODE:
        candidates += keyword_completions(statements_only=after_hash)
    candidates += [entry_completion(entry) for entry in scope.values()]
    preferred = frozenset(definition.label for definition in definitions)
    items = tuple(
        with_call_parentheses(item, next_character) for item in ranked(candidates, prefix, preferred)
    )
    if not explicit and is_already_complete(items, prefix):
        return None
    return CompletionResult(start, position, prefix, items)

from bisect import bisect_right
from dataclasses import dataclass

from typki.typst_syntax.lexer import SPAN_KINDS, Kind, Token


@dataclass(frozen=True)
class StyledRange:
    start: int
    end: int
    kind: Kind
    enclosing: frozenset[Kind] = frozenset()


class Coverage:
    def __init__(self, spans: list[Token]) -> None:
        self.starts: list[int] = []
        self.ends: list[int] = []
        for span in sorted(spans, key=lambda span: span.start):
            if self.ends and span.start <= self.ends[-1]:
                self.ends[-1] = max(self.ends[-1], span.end)
            else:
                self.starts.append(span.start)
                self.ends.append(span.end)

    def covers(self, position: int) -> bool:
        index = bisect_right(self.starts, position) - 1
        return index >= 0 and position < self.ends[index]


def styled_ranges(tokens: tuple[Token, ...]) -> list[StyledRange]:
    spans = [token for token in tokens if token.kind in SPAN_KINDS]
    coverage = {kind: Coverage([span for span in spans if span.kind == kind]) for kind in SPAN_KINDS}
    ranges = [StyledRange(span.start, span.end, span.kind) for span in spans]
    for token in tokens:
        if token.kind in SPAN_KINDS:
            continue
        enclosing = frozenset(kind for kind in SPAN_KINDS if coverage[kind].covers(token.start))
        ranges.append(StyledRange(token.start, token.end, token.kind, enclosing))
    return ranges

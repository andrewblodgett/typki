import re
from bisect import bisect_left

ASTRAL_CHARACTER = re.compile("[\U00010000-\U0010ffff]")


class TextPositions:
    def __init__(self, text: str) -> None:
        self.astral_indexes = [match.start() for match in ASTRAL_CHARACTER.finditer(text)]
        self.astral_positions = [index + count for count, index in enumerate(self.astral_indexes)]

    def to_qt(self, index: int) -> int:
        return index + bisect_left(self.astral_indexes, index) if self.astral_indexes else index

    def from_qt(self, position: int) -> int:
        return position - bisect_left(self.astral_positions, position) if self.astral_positions else position

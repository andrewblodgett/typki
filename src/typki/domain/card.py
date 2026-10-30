import uuid
from dataclasses import dataclass, field, replace


def new_source_id() -> str:
    return str(uuid.uuid4())


@dataclass(frozen=True)
class CardDraft:
    deck_name: str
    template_name: str
    tags: tuple[str, ...]
    front: str
    back: str
    source_id: str = field(default_factory=new_source_id)
    note_id: int | None = None

    @property
    def is_editing(self) -> bool:
        return self.note_id is not None

    def next_blank(self, front: str, back: str) -> CardDraft:
        return replace(self, front=front, back=back, source_id=new_source_id(), note_id=None)


@dataclass(frozen=True)
class StoredCard:
    note_id: int
    deck_name: str
    tags: tuple[str, ...]
    front_source: str
    back_source: str
    source_id: str
    preamble_hash: str
    renderer_version: str
    front_svg: str
    back_svg: str
    card_ids: tuple[int, ...]
    modified: int


def parse_tags(text: str) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for tag in text.split():
        seen.setdefault(tag, None)
    return tuple(seen)

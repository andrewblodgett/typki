import uuid
from dataclasses import dataclass, field


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

    def as_draft(self, template_name: str = "") -> CardDraft:
        return CardDraft(
            deck_name=self.deck_name,
            template_name=template_name,
            tags=self.tags,
            front=self.front_source,
            back=self.back_source,
            source_id=self.source_id or new_source_id(),
            note_id=self.note_id,
        )


def parse_tags(text: str) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for tag in text.split():
        seen.setdefault(tag, None)
    return tuple(seen)

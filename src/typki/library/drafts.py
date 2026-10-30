import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from typki.domain.card import CardDraft
from typki.library.store import write_text_atomically


class DraftStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def save(self, draft: CardDraft) -> None:
        write_text_atomically(self.path, json.dumps(asdict(draft), ensure_ascii=False, indent=2))

    def load(self) -> CardDraft | None:
        try:
            return draft_from_dict(json.loads(self.path.read_text(encoding="utf-8")))
        except OSError, ValueError, KeyError, TypeError:
            return None


def draft_from_dict(data: dict[str, Any]) -> CardDraft:
    return CardDraft(
        deck_name=str(data["deck_name"]),
        template_name=str(data.get("template_name", "")),
        tags=tuple(str(tag) for tag in data.get("tags", [])),
        front=str(data.get("front", "")),
        back=str(data.get("back", "")),
        source_id=str(data["source_id"]),
        note_id=int(data["note_id"]) if data.get("note_id") is not None else None,
    )

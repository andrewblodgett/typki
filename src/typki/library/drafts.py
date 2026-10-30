import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from typki.domain.card import CardDraft


class DraftStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def save(self, draft: CardDraft) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(asdict(draft), ensure_ascii=False, indent=2)
        descriptor, temporary_name = tempfile.mkstemp(dir=self.path.parent, prefix=".draft-")
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, self.path)

    def load(self) -> CardDraft | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return CardDraft(
                deck_name=str(data["deck_name"]),
                template_name=str(data["template_name"]),
                tags=tuple(str(tag) for tag in data.get("tags", [])),
                front=str(data.get("front", "")),
                back=str(data.get("back", "")),
                source_id=str(data["source_id"]),
                note_id=int(data["note_id"]) if data.get("note_id") is not None else None,
            )
        except OSError, ValueError, KeyError, TypeError:
            return None

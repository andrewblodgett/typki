import json
from dataclasses import asdict
from pathlib import Path

from typki.domain.card import CardDraft
from typki.library.drafts import draft_from_dict
from typki.library.store import write_text_atomically


class Outbox:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def path_for(self, source_id: str) -> Path:
        return self.directory / f"{source_id}.json"

    def put(self, draft: CardDraft) -> None:
        write_text_atomically(self.path_for(draft.source_id), json.dumps(asdict(draft), ensure_ascii=False))

    def remove(self, source_id: str) -> None:
        self.path_for(source_id).unlink(missing_ok=True)

    def drafts(self) -> list[CardDraft]:
        if not self.directory.is_dir():
            return []
        paths = sorted(self.directory.glob("*.json"), key=lambda path: path.stat().st_mtime)
        drafts = []
        for path in paths:
            try:
                drafts.append(draft_from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except OSError, ValueError, KeyError, TypeError:
                continue
        return drafts

    def count(self) -> int:
        return len(list(self.directory.glob("*.json"))) if self.directory.is_dir() else 0

from pathlib import Path

from typki.domain.card import CardDraft
from typki.library.drafts import read_draft, write_draft


class Outbox:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def path_for(self, source_id: str) -> Path:
        return self.directory / f"{source_id}.json"

    def put(self, draft: CardDraft) -> None:
        write_draft(self.path_for(draft.source_id), draft)

    def remove(self, source_id: str) -> None:
        self.path_for(source_id).unlink(missing_ok=True)

    def paths(self) -> list[Path]:
        return list(self.directory.glob("*.json")) if self.directory.is_dir() else []

    def drafts(self) -> list[CardDraft]:
        paths = sorted(self.paths(), key=lambda path: path.stat().st_mtime)
        return [draft for draft in map(read_draft, paths) if draft is not None]

    def count(self) -> int:
        return len(self.paths())

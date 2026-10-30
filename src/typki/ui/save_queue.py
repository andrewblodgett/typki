from PySide6.QtCore import QObject, Signal

from typki.anki.gateway import AnkiUnavailableError, DuplicateNoteError
from typki.card_service import CardService, RenderFailedError, SaveResult
from typki.domain.card import CardDraft
from typki.library.outbox import Outbox
from typki.ui.background import TaskRunner

SAVED = "Saved"
NOT_SAVED_COMPILE = "Not saved: compile error"
NOT_SAVED_DUPLICATE = "Not saved: duplicate front"


class SaveQueue(QObject):
    state_changed = Signal()
    saved = Signal(object, object)
    went_offline = Signal()

    def __init__(
        self, service: CardService, runner: TaskRunner, outbox: Outbox, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.runner = runner
        self.outbox = outbox
        self.pending: list[CardDraft] = []
        self.busy = False
        self.in_flight_source = ""
        self.offline = False
        self.status_by_source: dict[str, str] = {}

    @property
    def idle(self) -> bool:
        return not self.busy and not self.pending

    def is_saving(self, source_id: str) -> bool:
        in_flight = self.busy and self.in_flight_source == source_id
        return in_flight or any(draft.source_id == source_id for draft in self.pending)

    def enqueue(self, draft: CardDraft) -> None:
        if self.offline:
            self.outbox.put(draft)
            self.state_changed.emit()
            return
        self.pending = [queued for queued in self.pending if queued.source_id != draft.source_id]
        self.pending.append(draft)
        self.state_changed.emit()
        self.process()

    def go_online(self) -> None:
        self.offline = False
        for draft in self.outbox.drafts():
            if not any(queued.source_id == draft.source_id for queued in self.pending):
                self.pending.append(draft)
        self.state_changed.emit()
        self.process()

    def process(self) -> None:
        if self.busy or not self.pending:
            return
        draft = self.pending.pop(0)
        self.busy = True
        self.in_flight_source = draft.source_id
        self.runner.run(
            lambda: self.service.save(draft),
            lambda result: self.on_saved(draft, result),
            lambda error: self.on_failed(draft, error),
        )

    def on_saved(self, draft: CardDraft, result: SaveResult) -> None:
        self.busy = False
        self.outbox.remove(draft.source_id)
        self.status_by_source[draft.source_id] = SAVED
        self.saved.emit(draft.source_id, result)
        self.state_changed.emit()
        self.process()

    def on_failed(self, draft: CardDraft, error: Exception) -> None:
        self.busy = False
        if isinstance(error, AnkiUnavailableError):
            self.offline = True
            for queued in [draft, *self.pending]:
                self.outbox.put(queued)
            self.pending.clear()
            self.went_offline.emit()
            self.state_changed.emit()
            return
        self.outbox.remove(draft.source_id)
        if isinstance(error, RenderFailedError):
            self.status_by_source[draft.source_id] = NOT_SAVED_COMPILE
        elif isinstance(error, DuplicateNoteError):
            self.status_by_source[draft.source_id] = NOT_SAVED_DUPLICATE
        else:
            self.status_by_source[draft.source_id] = f"Not saved: {error}"
        self.state_changed.emit()
        self.process()

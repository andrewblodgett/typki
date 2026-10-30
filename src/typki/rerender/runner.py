import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from typki.anki import note_type
from typki.card_service import CardService, note_type_query, to_stored_card
from typki.domain.card import CardDraft
from typki.domain.preamble import Preamble
from typki.render.diagnostics import Diagnostic
from typki.render.plain_text import plain_text_from_source
from typki.rerender.plan import StalenessReport, chunked, fresh_notes_query

CHUNK_SIZE = 25


@dataclass(frozen=True)
class RerenderFailure:
    note_id: int
    deck_name: str
    title: str
    reason: str
    diagnostics: tuple[Diagnostic, ...] = ()


@dataclass(frozen=True)
class RerenderProgress:
    done: int
    total: int


@dataclass
class RerenderReport:
    applied: bool
    checked: int = 0
    compiled: list[int] = field(default_factory=list)
    updated: list[int] = field(default_factory=list)
    failures: list[RerenderFailure] = field(default_factory=list)
    cancelled: bool = False


@dataclass(frozen=True)
class FailureGroup:
    diagnostic: Diagnostic | None
    failures: tuple[RerenderFailure, ...]

    @property
    def shared(self) -> bool:
        return self.diagnostic is not None


def shared_library_diagnostic(failure: RerenderFailure) -> Diagnostic | None:
    return next((diagnostic for diagnostic in failure.diagnostics if diagnostic.file), None)


def group_failures(failures: list[RerenderFailure]) -> list[FailureGroup]:
    shared: dict[str, list[RerenderFailure]] = {}
    shared_diagnostics: dict[str, Diagnostic] = {}
    singles: list[FailureGroup] = []
    for failure in failures:
        diagnostic = shared_library_diagnostic(failure)
        if diagnostic is None:
            singles.append(FailureGroup(None, (failure,)))
            continue
        key = diagnostic.describe()
        shared.setdefault(key, []).append(failure)
        shared_diagnostics[key] = diagnostic
    groups = [FailureGroup(shared_diagnostics[key], tuple(items)) for key, items in shared.items()]
    return groups + singles


ProgressCallback = Callable[[RerenderProgress], None]


class Rerenderer:
    def __init__(self, service: CardService) -> None:
        self.service = service

    def staleness(self) -> StalenessReport:
        gateway = self.service.gateway
        type_query = note_type_query()
        note_ids = gateway.find_notes(type_query)
        if not note_ids:
            return StalenessReport(stale_note_ids=(), total=0)
        preamble_hash = self.service.library.preamble().hash
        renderer_version = self.service.renderer.renderer_version
        fresh = set(gateway.find_notes(fresh_notes_query(type_query, preamble_hash, renderer_version)))
        stale = tuple(sorted(note_id for note_id in note_ids if note_id not in fresh))
        return StalenessReport(stale_note_ids=stale, total=len(note_ids))

    def run(
        self,
        note_ids: tuple[int, ...],
        apply: bool,
        progress: ProgressCallback | None = None,
        cancel: threading.Event | None = None,
    ) -> RerenderReport:
        report = RerenderReport(applied=apply)
        preamble = self.service.library.preamble()
        processed = 0
        for chunk in chunked(note_ids, CHUNK_SIZE):
            if cancel is not None and cancel.is_set():
                report.cancelled = True
                break
            with self.service.write_lock:
                self.process_chunk(chunk, preamble, apply, report)
            processed += len(chunk)
            if progress is not None:
                progress(RerenderProgress(done=processed, total=len(note_ids)))
        return report

    def process_chunk(
        self, chunk: list[int], preamble: Preamble, apply: bool, report: RerenderReport
    ) -> None:
        updates: list[tuple[int, dict[str, str]]] = []
        for record in self.service.gateway.notes_info(chunk):
            if record.model_name != note_type.NOTE_TYPE_NAME:
                continue
            card = to_stored_card(record)
            report.checked += 1
            card_render = self.service.render_with(preamble, card.front_source, card.back_source)
            title = plain_text_from_source(card.front_source)[:80] or f"Note {card.note_id}"
            if not card_render.ok:
                report.failures.append(
                    RerenderFailure(
                        card.note_id,
                        card.deck_name,
                        title,
                        "compile error",
                        card_render.front.errors + card_render.back.errors,
                    )
                )
                continue
            report.compiled.append(card.note_id)
            draft = CardDraft(
                deck_name=card.deck_name,
                template_name="",
                tags=card.tags,
                front=card.front_source,
                back=card.back_source,
                source_id=card.source_id,
                note_id=card.note_id,
            )
            updates.append((card.note_id, self.service.rendered_fields(draft, card_render)))
        if apply and updates:
            errors = self.service.gateway.update_many_note_fields(updates)
            for (note_id, _), error in zip(updates, errors, strict=True):
                if error is None:
                    report.updated.append(note_id)
                else:
                    report.failures.append(RerenderFailure(note_id, "", f"Note {note_id}", error))

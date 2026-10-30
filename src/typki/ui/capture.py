from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import QComboBox, QLabel, QPushButton, QWidget

from typki.card_service import CardRender, CardService, SaveResult
from typki.domain.card import CardDraft, StoredCard, missing_content, new_source_id, parse_tags
from typki.domain.template import (
    BLANK,
    PLACEHOLDER_PATTERN,
    Template,
    find_template,
    retag_for_template,
    template_for_tags,
    templates_from_header,
)
from typki.library.drafts import DraftStore
from typki.ui.background import CoalescingTask, TaskRunner, debouncer
from typki.ui.editor import TypstEditor
from typki.ui.editor_field import EditorField
from typki.ui.layout import page, panel, row, splitter
from typki.ui.preview import CardPreview
from typki.ui.save_queue import NOT_SAVED, SaveQueue
from typki.ui.tags_edit import TagsEdit
from typki.ui.theme import Theme

RENDER_DEBOUNCE_MS = 60
AUTOSAVE_DEBOUNCE_MS = 400
DRAFT_SAVE_DEBOUNCE_MS = 400
DECK_WIDTH = 220
TEMPLATE_WIDTH = 160
SAVE_STATUS_WIDTH = 260
DEFAULT_DECK = "Default"
FRONT = "front"
BACK = "back"

Snapshot = tuple[str, tuple[str, ...], str, str]


class DeckComboBox(QComboBox):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        line_edit = self.lineEdit()
        if line_edit is not None:
            line_edit.setPlaceholderText("Deck")
            line_edit.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            watched is self.lineEdit()
            and event.type() == QEvent.Type.MouseButtonRelease
            and not self.view().isVisible()
            and self.count()
        ):
            self.showPopup()
        return super().eventFilter(watched, event)

    def set_names(self, deck_names: Iterable[str]) -> None:
        current = self.currentText().strip() or DEFAULT_DECK
        was_blocked = self.blockSignals(True)
        self.clear()
        self.addItems(sorted(set(deck_names) | {current}))
        self.setCurrentText(current)
        self.blockSignals(was_blocked)

    def remember(self, deck_name: str) -> None:
        if deck_name and self.findText(deck_name, Qt.MatchFlag.MatchFixedString) < 0:
            self.set_names([*map(self.itemText, range(self.count())), deck_name])


class CapturePage(QWidget):
    save_state_changed = Signal()

    def __init__(
        self,
        service: CardService,
        render_runner: TaskRunner,
        save_queue: SaveQueue,
        draft_store: DraftStore,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.save_queue = save_queue
        self.draft_store = draft_store
        self.source_id = new_source_id()
        self.note_id: int | None = None
        self.header_text = service.library.read_header()
        self.templates: tuple[Template, ...] = templates_from_header(self.header_text)
        self.saved_snapshot: Snapshot | None = None
        self.last_render_ok = False
        self.restoring = False

        self.deck_combo = DeckComboBox()
        self.deck_combo.setMinimumWidth(DECK_WIDTH)
        self.deck_combo.set_names([DEFAULT_DECK])
        self.template_combo = QComboBox()
        self.template_combo.setMinimumWidth(TEMPLATE_WIDTH)
        self.fill_template_combo()
        self.tags_edit = TagsEdit()
        self.tags_edit.setPlaceholderText("Tags")
        self.front_editor = TypstEditor()
        self.back_editor = TypstEditor()
        for editor in (self.front_editor, self.back_editor):
            editor.definitions_source = lambda: self.header_text
            editor.textChanged.connect(self.on_source_changed)
        self.front_field = EditorField("Front", self.front_editor)
        self.back_field = EditorField("Back", self.back_editor)
        self.preview = CardPreview()
        self.save_status_label = QLabel()
        self.save_status_label.setObjectName("save-status")
        self.save_new_button = QPushButton("Save && new")
        self.save_new_button.setObjectName("primary")
        self.save_new_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        toolbar = row(
            self.deck_combo,
            self.template_combo,
            (self.tags_edit, 1),
            self.save_status_label,
            self.save_new_button,
        )
        editors = panel((self.front_field, 1), (self.back_field, 1), spacing=0)
        page(self, toolbar, (splitter(editors, self.preview), 1))

        self.render_task = CoalescingTask(
            render_runner, self.render_job, self.on_rendered, self.on_render_crashed
        )
        self.render_timer = debouncer(self, RENDER_DEBOUNCE_MS, self.request_render)
        self.autosave_timer = debouncer(self, AUTOSAVE_DEBOUNCE_MS, self.autosave)
        self.draft_timer = debouncer(self, DRAFT_SAVE_DEBOUNCE_MS, self.save_draft)
        self.tags_edit.textChanged.connect(self.on_metadata_changed)
        self.deck_combo.currentTextChanged.connect(self.on_metadata_changed)
        self.template_combo.activated.connect(lambda _index: self.discard_card(self.template_key()))
        self.save_new_button.clicked.connect(self.new_card)
        self.save_state_changed.connect(self.refresh_save_status)
        save_queue.state_changed.connect(self.refresh_save_status)
        save_queue.saved.connect(self.on_saved)

    def fill_template_combo(self) -> None:
        current = self.template_combo.currentData()
        was_blocked = self.template_combo.blockSignals(True)
        self.template_combo.clear()
        for template in self.templates:
            self.template_combo.addItem(template.title, template.name)
        self.template_combo.setCurrentIndex(max(self.template_combo.findData(current), 0))
        self.template_combo.blockSignals(was_blocked)

    def refresh_templates(self) -> None:
        self.header_text = self.service.library.read_header()
        self.templates = templates_from_header(self.header_text)
        self.fill_template_combo()

    def deck_name(self) -> str:
        return self.deck_combo.currentText().strip() or DEFAULT_DECK

    def template_key(self) -> str:
        return str(self.template_combo.currentData() or "")

    def current_draft(self) -> CardDraft:
        return CardDraft(
            deck_name=self.deck_name(),
            template_name=self.template_key(),
            tags=parse_tags(self.tags_edit.text()),
            front=self.front_editor.toPlainText(),
            back=self.back_editor.toPlainText(),
            source_id=self.source_id,
            note_id=self.note_id,
        )

    def snapshot(self) -> Snapshot:
        draft = self.current_draft()
        return (draft.deck_name, draft.tags, draft.front, draft.back)

    def missing_content(self) -> str | None:
        return missing_content(self.front_editor.toPlainText(), self.back_editor.toPlainText())

    def is_savable(self) -> bool:
        return self.missing_content() is None and self.snapshot() != self.saved_snapshot

    def can_leave_card(self) -> bool:
        front, back = self.front_editor.toPlainText(), self.back_editor.toPlainText()
        missing = missing_content(front, back)
        if missing is None or not (front.strip() or back.strip()) or self.snapshot() == self.saved_snapshot:
            return True
        if not front.strip() or not back.strip():
            field = self.front_field if not front.strip() else self.back_field
        else:
            field = self.front_field if PLACEHOLDER_PATTERN.search(front) else self.back_field
            field.editor.select_placeholder(forward=True, from_position=0)
        field.show_problem(missing)
        field.editor.setFocus()
        return False

    def save_status(self) -> str:
        if self.autosave_timer.isActive() or self.save_queue.is_saving(self.source_id):
            return "Saving…"
        return self.save_queue.status_by_source.get(self.source_id, "")

    def refresh_save_status(self) -> None:
        status = self.save_status()
        label = self.save_status_label
        label.setText(label.fontMetrics().elidedText(status, Qt.TextElideMode.ElideRight, SAVE_STATUS_WIDTH))
        label.setToolTip(status)
        label.setProperty("level", "error" if status.startswith(NOT_SAVED) else "")
        label.style().polish(label)

    @contextmanager
    def loading_fields(self) -> Iterator[None]:
        self.restoring = True
        try:
            yield
        finally:
            self.restoring = False

    def show_draft(self, draft: CardDraft, saved: bool) -> None:
        with self.loading_fields():
            self.deck_combo.setCurrentText(draft.deck_name)
            self.select_template_key(draft.template_name)
            self.tags_edit.setText(" ".join(draft.tags))
            self.back_editor.setPlainText(draft.back)
            self.front_editor.set_source(draft.front)
            self.source_id, self.note_id = draft.source_id, draft.note_id
        self.saved_snapshot = self.snapshot() if saved else None
        self.front_editor.setFocus()
        self.request_render()
        self.save_draft()
        self.save_state_changed.emit()

    def restore(self, draft: CardDraft | None) -> None:
        if draft is None:
            self.start_new_card(BLANK.name)
        else:
            self.show_draft(draft, saved=False)

    def select_template_key(self, name: str) -> None:
        index = self.template_combo.findData(find_template(name, self.templates).name)
        self.template_combo.setCurrentIndex(max(index, 0))

    def new_card(self) -> None:
        if not self.can_leave_card():
            return
        self.flush()
        self.start_new_card(self.template_key())

    def discard_card(self, template_name: str) -> None:
        self.autosave_timer.stop()
        self.start_new_card(template_name)

    def start_new_card(self, template_name: str) -> None:
        template = find_template(template_name, self.templates)
        tags = retag_for_template(parse_tags(self.tags_edit.text()), template, self.templates)
        self.show_draft(CardDraft(self.deck_name(), template.name, tags, template.front, ""), saved=True)

    def load_card(self, card: StoredCard) -> None:
        if not self.can_leave_card():
            return
        self.flush()
        self.show_draft(card.as_draft(template_for_tags(card.tags, self.templates).name), saved=True)

    def discard_if_showing(self, note_id: int) -> None:
        if self.note_id == note_id:
            self.discard_card(BLANK.name)

    def on_source_changed(self) -> None:
        if self.restoring:
            return
        self.last_render_ok = False
        self.autosave_timer.stop()
        self.render_timer.start()
        self.draft_timer.start()

    def on_metadata_changed(self) -> None:
        if self.restoring:
            return
        self.draft_timer.start()
        self.schedule_autosave()

    def schedule_autosave(self) -> None:
        if self.last_render_ok and self.is_savable():
            self.autosave_timer.start()
        self.save_state_changed.emit()

    def autosave(self) -> None:
        if self.is_savable():
            self.saved_snapshot = self.snapshot()
            self.save_queue.enqueue(self.current_draft())
        self.save_state_changed.emit()

    def flush(self) -> None:
        self.autosave_timer.stop()
        if self.is_savable():
            self.autosave()

    def on_saved(self, source_id: str, result: SaveResult) -> None:
        if source_id == self.source_id:
            self.note_id = result.note_id
        self.deck_combo.remember(self.deck_name())
        self.tags_edit.add_known_tags(parse_tags(self.tags_edit.text()))

    def save_draft(self) -> None:
        self.draft_store.save(self.current_draft())

    def request_render(self) -> None:
        self.render_task.request()

    def render_job(self) -> Callable[[], CardRender]:
        front, back = self.front_editor.toPlainText(), self.back_editor.toPlainText()
        return lambda: self.service.render(front, back)

    def on_rendered(self, card_render: CardRender) -> None:
        sides = ((FRONT, card_render.front, self.front_field), (BACK, card_render.back, self.back_field))
        for side, side_render, field in sides:
            self.preview.set_side(side, side_render.svg, not side_render.ok)
            field.show_diagnostics(list(side_render.diagnostics))
        self.last_render_ok = card_render.ok
        self.schedule_autosave()

    def on_render_crashed(self, error: Exception) -> None:
        self.front_field.show_problem(str(error))

    def set_theme(self, theme: Theme) -> None:
        for themed in (self.front_field, self.back_field, self.preview):
            themed.set_theme(theme)

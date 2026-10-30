from collections.abc import Sequence

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from typki.card_service import CardRender, CardService, SaveResult
from typki.domain.card import CardDraft, StoredCard, new_source_id, parse_tags
from typki.domain.template import BLANK, PLACEHOLDER_PATTERN, Template, find_template, templates_from_header
from typki.library.drafts import DraftStore
from typki.render.compiler import SideRender
from typki.render.diagnostics import Diagnostic
from typki.ui.background import TaskRunner
from typki.ui.editor import TypstEditor
from typki.ui.preview import CardPreview
from typki.ui.save_queue import SaveQueue
from typki.ui.tags_edit import TagsEdit

RENDER_DEBOUNCE_MS = 60
AUTOSAVE_DEBOUNCE_MS = 400
DRAFT_SAVE_DEBOUNCE_MS = 400
DEFAULT_DECK = "Default"
FRONT = "front"
BACK = "back"
DIAGNOSTIC_ROLE = Qt.ItemDataRole.UserRole

Snapshot = tuple[str, tuple[str, ...], str, str]


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
        self.render_runner = render_runner
        self.save_queue = save_queue
        self.draft_store = draft_store
        self.source_id = new_source_id()
        self.note_id: int | None = None
        self.templates: tuple[Template, ...] = templates_from_header(service.library.read_header())
        self.saved_snapshot: Snapshot | None = None
        self.last_render_ok = False
        self.render_in_flight = False
        self.render_pending = False
        self.restoring = False

        self.deck_combo = QComboBox()
        self.deck_combo.setEditable(True)
        self.deck_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.deck_combo.setMinimumWidth(220)
        self.template_combo = QComboBox()
        self.fill_template_combo()
        self.tags_edit = TagsEdit()
        self.front_editor = TypstEditor()
        self.back_editor = TypstEditor()
        self.diagnostics_list = QListWidget()
        self.diagnostics_list.setMaximumHeight(110)
        self.diagnostics_list.setVisible(False)
        self.preview = CardPreview()

        self.build_layout()

        self.render_timer = QTimer(self, singleShot=True, interval=RENDER_DEBOUNCE_MS)
        self.render_timer.timeout.connect(self.request_render)
        self.autosave_timer = QTimer(self, singleShot=True, interval=AUTOSAVE_DEBOUNCE_MS)
        self.autosave_timer.timeout.connect(self.autosave)
        self.draft_timer = QTimer(self, singleShot=True, interval=DRAFT_SAVE_DEBOUNCE_MS)
        self.draft_timer.timeout.connect(self.save_draft)

        self.front_editor.textChanged.connect(self.on_source_changed)
        self.back_editor.textChanged.connect(self.on_source_changed)
        self.tags_edit.textChanged.connect(self.on_metadata_changed)
        self.deck_combo.currentTextChanged.connect(self.on_metadata_changed)
        self.template_combo.activated.connect(self.on_template_chosen)
        self.diagnostics_list.itemActivated.connect(self.on_diagnostic_activated)
        self.diagnostics_list.itemClicked.connect(self.on_diagnostic_activated)
        save_queue.saved.connect(self.on_saved)

    def build_layout(self) -> None:
        form = QFormLayout()
        form.addRow("Deck", self.deck_combo)
        form.addRow("Template", self.template_combo)
        form.addRow("Tags", self.tags_edit)

        editors = QWidget()
        editors_layout = QVBoxLayout(editors)
        editors_layout.setContentsMargins(0, 0, 0, 0)
        editors_layout.addWidget(QLabel("Front"))
        editors_layout.addWidget(self.front_editor, 1)
        editors_layout.addWidget(QLabel("Back"))
        editors_layout.addWidget(self.back_editor, 1)
        editors_layout.addWidget(self.diagnostics_list)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(editors)
        splitter.addWidget(self.preview)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(splitter, 1)

    def fill_template_combo(self) -> None:
        current = self.template_combo.currentData()
        self.template_combo.blockSignals(True)
        self.template_combo.clear()
        for template in self.templates:
            self.template_combo.addItem(template.title, template.name)
        self.template_combo.setCurrentIndex(max(self.template_combo.findData(current), 0))
        self.template_combo.blockSignals(False)

    def refresh_templates(self) -> None:
        self.templates = templates_from_header(self.service.library.read_header())
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

    def is_savable(self) -> bool:
        front = self.front_editor.toPlainText()
        back = self.back_editor.toPlainText()
        if not front.strip() or PLACEHOLDER_PATTERN.search(front) or PLACEHOLDER_PATTERN.search(back):
            return False
        return self.snapshot() != self.saved_snapshot

    def save_status(self) -> str:
        if self.autosave_timer.isActive() or self.save_queue.is_saving(self.source_id):
            return "Saving…"
        return self.save_queue.status_by_source.get(self.source_id, "")

    def set_deck_names(self, deck_names: list[str]) -> None:
        current = self.deck_name()
        self.deck_combo.blockSignals(True)
        self.deck_combo.clear()
        self.deck_combo.addItems(sorted(set(deck_names) | {current}))
        self.deck_combo.setCurrentText(current)
        self.deck_combo.blockSignals(False)

    def restore(self, draft: CardDraft | None) -> None:
        if draft is None:
            self.restoring = True
            self.deck_combo.setCurrentText(DEFAULT_DECK)
            self.restoring = False
            self.start_new_card(BLANK.name)
            return
        self.restoring = True
        self.deck_combo.setCurrentText(draft.deck_name)
        self.select_template_key(draft.template_name)
        self.tags_edit.setText(" ".join(draft.tags))
        self.front_editor.setPlainText(draft.front)
        self.back_editor.setPlainText(draft.back)
        self.source_id = draft.source_id
        self.note_id = draft.note_id
        self.saved_snapshot = None
        self.restoring = False
        self.request_render()

    def select_template_key(self, name: str) -> None:
        index = self.template_combo.findData(find_template(name, self.templates).name)
        self.template_combo.setCurrentIndex(max(index, 0))

    def on_template_chosen(self, _index: int) -> None:
        self.new_card(self.template_key())

    def new_card(self, template_name: str | None = None) -> None:
        self.flush()
        self.start_new_card(self.template_key() if template_name is None else template_name)

    def start_new_card(self, template_name: str) -> None:
        template = find_template(template_name, self.templates)
        self.restoring = True
        self.note_id = None
        self.source_id = new_source_id()
        self.select_template_key(template.name)
        self.back_editor.setPlainText("")
        self.front_editor.set_source(template.front)
        self.restoring = False
        self.saved_snapshot = self.snapshot()
        self.preview.clear()
        self.show_diagnostic_lines([])
        self.front_editor.setFocus()
        self.request_render()
        self.save_draft()
        self.save_state_changed.emit()

    def load_card(self, card: StoredCard) -> None:
        self.flush()
        self.restoring = True
        self.note_id = card.note_id
        self.source_id = card.source_id or new_source_id()
        self.deck_combo.setCurrentText(card.deck_name)
        self.tags_edit.setText(" ".join(card.tags))
        self.select_template_key(BLANK.name)
        self.front_editor.setPlainText(card.front_source)
        self.back_editor.setPlainText(card.back_source)
        self.restoring = False
        self.saved_snapshot = self.snapshot()
        self.save_draft()
        self.request_render()
        self.front_editor.setFocus()
        self.save_state_changed.emit()

    def discard_if_showing(self, note_id: int) -> None:
        if self.note_id == note_id:
            self.autosave_timer.stop()
            self.start_new_card(BLANK.name)

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
        self.tags_edit.add_known_tags(parse_tags(self.tags_edit.text()))

    def save_draft(self) -> None:
        self.draft_store.save(self.current_draft())

    def request_render(self) -> None:
        if self.render_in_flight:
            self.render_pending = True
            return
        self.render_in_flight = True
        front = self.front_editor.toPlainText()
        back = self.back_editor.toPlainText()
        self.render_runner.run(
            lambda: self.service.render(front, back),
            self.on_rendered,
            self.on_render_crashed,
        )

    def finish_render_cycle(self) -> bool:
        self.render_in_flight = False
        if self.render_pending:
            self.render_pending = False
            self.request_render()
            return False
        return True

    def on_rendered(self, card_render: CardRender) -> None:
        if not self.finish_render_cycle():
            return
        self.show_side(FRONT, card_render.front, self.front_editor)
        self.show_side(BACK, card_render.back, self.back_editor)
        lines = [(FRONT, d) for d in card_render.front.diagnostics]
        lines += [(BACK, d) for d in card_render.back.diagnostics]
        self.show_diagnostic_lines(lines)
        self.last_render_ok = card_render.ok
        self.schedule_autosave()

    def on_render_crashed(self, error: Exception) -> None:
        if self.finish_render_cycle():
            self.show_diagnostic_lines([(None, Diagnostic("error", str(error)))])

    def show_side(self, side: str, side_render: SideRender, editor: TypstEditor) -> None:
        self.preview.set_side(side, side_render.svg, not side_render.ok)
        editor.show_diagnostics(list(side_render.diagnostics))

    def show_diagnostic_lines(self, lines: Sequence[tuple[str | None, Diagnostic]]) -> None:
        self.diagnostics_list.clear()
        for side, diagnostic in lines:
            side_label = f"{side.capitalize()} " if side and diagnostic.in_card else ""
            item = QListWidgetItem(f"{side_label}{diagnostic.describe()}")
            item.setData(DIAGNOSTIC_ROLE, (side, diagnostic))
            color = Qt.GlobalColor.red if diagnostic.severity == "error" else Qt.GlobalColor.darkYellow
            item.setForeground(color)
            self.diagnostics_list.addItem(item)
        self.diagnostics_list.setVisible(bool(lines))

    def on_diagnostic_activated(self, item: QListWidgetItem) -> None:
        side, diagnostic = item.data(DIAGNOSTIC_ROLE)
        if not diagnostic.in_card or diagnostic.line is None:
            return
        editor = self.front_editor if side == FRONT else self.back_editor
        editor.jump_to(diagnostic.line, diagnostic.column or 1)

    def focus_front(self) -> None:
        self.front_editor.setFocus()

    def focus_back(self) -> None:
        self.back_editor.setFocus()

    def toggle_dark(self) -> None:
        self.preview.dark_toggle.toggle()

    def toggle_phone(self) -> None:
        self.preview.phone_toggle.toggle()

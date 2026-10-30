from collections.abc import Callable, Sequence

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from typki.anki.gateway import AnkiUnavailableError, DuplicateNoteError
from typki.card_service import CardRender, CardService, OpenedCard, RenderFailedError, SaveResult
from typki.domain.card import CardDraft, new_source_id, parse_tags
from typki.domain.template import BLANK, Template, find_template, templates_from_header
from typki.library.drafts import DraftStore
from typki.render.compiler import SideRender
from typki.render.diagnostics import Diagnostic
from typki.ui.background import TaskRunner
from typki.ui.editor import TypstEditor
from typki.ui.preview import CardPreview

RENDER_DEBOUNCE_MS = 60
DRAFT_SAVE_DEBOUNCE_MS = 400
DEFAULT_DECK = "Default"
FRONT = "front"
BACK = "back"
DIAGNOSTIC_ROLE = Qt.ItemDataRole.UserRole


class CapturePage(QWidget):
    status_message = Signal(str)

    def __init__(
        self,
        service: CardService,
        render_runner: TaskRunner,
        anki_runner: TaskRunner,
        draft_store: DraftStore,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.render_runner = render_runner
        self.anki_runner = anki_runner
        self.draft_store = draft_store
        self.source_id = new_source_id()
        self.note_id: int | None = None
        self.templates: tuple[Template, ...] = templates_from_header(service.library.read_header())
        self.baseline = ("", "")
        self.applied_template_name = BLANK.name
        self.render_in_flight = False
        self.render_pending = False
        self.save_in_flight = False
        self.restoring = False

        self.deck_combo = QComboBox()
        self.deck_combo.setEditable(True)
        self.deck_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.deck_combo.setMinimumWidth(220)
        self.template_combo = QComboBox()
        self.fill_template_combo()
        self.tags_edit = QLineEdit()
        self.mode_label = QLabel()

        self.front_editor = TypstEditor()
        self.back_editor = TypstEditor()
        self.diagnostics_list = QListWidget()
        self.diagnostics_list.setMaximumHeight(110)
        self.preview = CardPreview()

        self.save_next_button = QPushButton("Save and next")
        self.save_stay_button = QPushButton("Save and stay")
        self.new_card_button = QPushButton("New card")

        self.build_layout()

        self.render_timer = QTimer(self, singleShot=True, interval=RENDER_DEBOUNCE_MS)
        self.render_timer.timeout.connect(self.request_render)
        self.draft_timer = QTimer(self, singleShot=True, interval=DRAFT_SAVE_DEBOUNCE_MS)
        self.draft_timer.timeout.connect(self.save_draft)

        self.front_editor.textChanged.connect(self.on_source_changed)
        self.back_editor.textChanged.connect(self.on_source_changed)
        self.tags_edit.textChanged.connect(self.on_form_changed)
        self.deck_combo.currentTextChanged.connect(self.on_deck_changed)
        self.template_combo.activated.connect(self.on_template_chosen)
        self.diagnostics_list.itemActivated.connect(self.on_diagnostic_activated)
        self.diagnostics_list.itemClicked.connect(self.on_diagnostic_activated)
        self.save_next_button.clicked.connect(self.save_and_next)
        self.save_stay_button.clicked.connect(self.save_and_stay)
        self.new_card_button.clicked.connect(self.new_card)

        self.update_mode_label()

    def build_layout(self) -> None:
        form = QFormLayout()
        form.addRow("Deck", self.deck_combo)
        form.addRow("Template", self.template_combo)
        form.addRow("Tags", self.tags_edit)

        header = QHBoxLayout()
        header.addLayout(form, 1)
        header.addWidget(self.mode_label, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)

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

        buttons = QHBoxLayout()
        buttons.addWidget(self.new_card_button)
        buttons.addStretch(1)
        buttons.addWidget(self.save_stay_button)
        buttons.addWidget(self.save_next_button)

        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(splitter, 1)
        layout.addLayout(buttons)

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

    def is_pristine(self) -> bool:
        return (self.front_editor.toPlainText(), self.back_editor.toPlainText()) == self.baseline

    def has_unsaved_new_card(self) -> bool:
        return self.note_id is None and not self.is_pristine()

    def set_deck_names(self, deck_names: list[str]) -> None:
        current = self.deck_name()
        self.deck_combo.blockSignals(True)
        self.deck_combo.clear()
        self.deck_combo.addItems(sorted(set(deck_names) | {current}))
        self.deck_combo.setCurrentText(current)
        self.deck_combo.blockSignals(False)

    def restore(self, draft: CardDraft | None) -> None:
        self.restoring = True
        if draft is None:
            self.deck_combo.setCurrentText(DEFAULT_DECK)
            self.apply_template(self.template_key())
        else:
            self.deck_combo.setCurrentText(draft.deck_name)
            self.select_template_key(draft.template_name)
            self.baseline = (find_template(draft.template_name, self.templates).front, "")
            self.applied_template_name = draft.template_name
            self.tags_edit.setText(" ".join(draft.tags))
            self.front_editor.setPlainText(draft.front)
            self.back_editor.setPlainText(draft.back)
            self.source_id = draft.source_id
            self.note_id = draft.note_id
        self.restoring = False
        self.update_mode_label()
        self.request_render()

    def select_template_key(self, name: str) -> None:
        index = self.template_combo.findData(find_template(name, self.templates).name)
        self.template_combo.setCurrentIndex(max(index, 0))

    def apply_template(self, name: str) -> None:
        template = find_template(name, self.templates)
        self.select_template_key(template.name)
        self.baseline = (template.front, "")
        self.applied_template_name = template.name
        self.back_editor.setPlainText("")
        self.front_editor.set_source(template.front)
        self.front_editor.setFocus()

    def on_template_chosen(self, _index: int) -> None:
        if not self.is_pristine():
            answer = QMessageBox.question(
                self,
                "Typki",
                "Replace the current card?",
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Ok:
                self.select_template_key(self.applied_template_name)
                return
        self.apply_template(self.template_key())

    def on_deck_changed(self, _text: str) -> None:
        self.on_form_changed()

    def on_source_changed(self) -> None:
        self.render_timer.start()
        self.on_form_changed()

    def on_form_changed(self) -> None:
        if not self.restoring:
            self.draft_timer.start()

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
        if self.finish_render_cycle():
            self.show_render(card_render)

    def on_render_crashed(self, error: Exception) -> None:
        if self.finish_render_cycle():
            self.show_diagnostic_lines([(None, Diagnostic("error", str(error)))])

    def show_render(self, card_render: CardRender) -> None:
        self.show_side(FRONT, card_render.front, self.front_editor)
        self.show_side(BACK, card_render.back, self.back_editor)
        lines = [(FRONT, d) for d in card_render.front.diagnostics]
        lines += [(BACK, d) for d in card_render.back.diagnostics]
        self.show_diagnostic_lines(lines)

    def show_side(self, side: str, side_render: SideRender, editor: TypstEditor) -> None:
        self.preview.set_side(side, side_render.svg, not side_render.ok)
        editor.show_diagnostics(list(side_render.diagnostics))

    def show_diagnostic_lines(self, lines: Sequence[tuple[str | None, Diagnostic]]) -> None:
        self.diagnostics_list.clear()
        for side, diagnostic in lines:
            side_label = f"{side.capitalize()} " if side and diagnostic.in_card else ""
            item = QListWidgetItem(f"{side_label}{diagnostic.describe()}")
            if diagnostic.hints:
                item.setToolTip("\n".join(diagnostic.hints))
            item.setData(DIAGNOSTIC_ROLE, (side, diagnostic))
            item.setForeground(
                Qt.GlobalColor.red if diagnostic.severity == "error" else Qt.GlobalColor.darkYellow
            )
            self.diagnostics_list.addItem(item)
        self.diagnostics_list.setVisible(bool(lines))

    def on_diagnostic_activated(self, item: QListWidgetItem) -> None:
        side, diagnostic = item.data(DIAGNOSTIC_ROLE)
        if not diagnostic.in_card or diagnostic.line is None:
            return
        editor = self.front_editor if side == FRONT else self.back_editor
        editor.jump_to(diagnostic.line, diagnostic.column or 1)

    def save_and_next(self) -> None:
        self.save(on_saved=self.after_save_and_next)

    def save_and_stay(self) -> None:
        self.save(on_saved=self.after_save_and_stay)

    def save(self, on_saved: Callable[[SaveResult], None]) -> None:
        if self.save_in_flight:
            return
        draft = self.current_draft()
        if not draft.front.strip():
            self.front_editor.setFocus()
            return
        self.set_saving(True)
        self.anki_runner.run(
            lambda: self.service.save(draft),
            lambda result: self.on_saved(result, draft, on_saved),
            self.on_save_failed,
        )

    def on_saved(self, result: SaveResult, draft: CardDraft, then: Callable[[SaveResult], None]) -> None:
        self.set_saving(False)
        self.status_message.emit("Saved")
        then(result)
        self.save_draft()

    def after_save_and_next(self, _result: SaveResult) -> None:
        self.start_new_card()

    def after_save_and_stay(self, result: SaveResult) -> None:
        self.note_id = result.note_id
        self.update_mode_label()

    def on_save_failed(self, error: Exception) -> None:
        self.set_saving(False)
        if isinstance(error, RenderFailedError):
            self.show_render(error.card_render)
            self.status_message.emit("Not saved: compile error")
        elif isinstance(error, DuplicateNoteError):
            self.status_message.emit("Not saved: duplicate front")
        elif isinstance(error, AnkiUnavailableError):
            self.status_message.emit("Not saved: Anki not reachable")
        else:
            QMessageBox.warning(self, "Typki", str(error))

    def set_saving(self, saving: bool) -> None:
        self.save_in_flight = saving
        for editor in (self.front_editor, self.back_editor):
            editor.setReadOnly(saving)
        for button in (self.save_next_button, self.save_stay_button):
            button.setEnabled(not saving)

    def new_card(self) -> None:
        if self.has_unsaved_new_card():
            answer = QMessageBox.question(
                self,
                "Typki",
                "Discard the unsaved card?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Discard:
                return
        self.start_new_card()

    def start_new_card(self) -> None:
        self.note_id = None
        self.source_id = new_source_id()
        self.preview.clear()
        self.show_diagnostic_lines([])
        self.apply_template(self.template_key())
        self.update_mode_label()

    def load_opened_card(self, opened: OpenedCard) -> None:
        card = opened.card
        self.restoring = True
        self.note_id = card.note_id
        self.source_id = card.source_id or new_source_id()
        self.deck_combo.setCurrentText(card.deck_name)
        self.tags_edit.setText(" ".join(card.tags))
        self.baseline = (card.front_source, card.back_source)
        self.applied_template_name = BLANK.name
        self.select_template_key(BLANK.name)
        self.front_editor.setPlainText(card.front_source)
        self.back_editor.setPlainText(card.back_source)
        self.restoring = False
        self.update_mode_label()
        self.save_draft()
        self.request_render()
        self.front_editor.setFocus()

    def update_mode_label(self) -> None:
        self.mode_label.setText("" if self.note_id is None else "Editing")

    def focus_front(self) -> None:
        self.front_editor.setFocus()

    def focus_back(self) -> None:
        self.back_editor.setFocus()

    def toggle_dark(self) -> None:
        self.preview.dark_toggle.toggle()

    def toggle_phone(self) -> None:
        self.preview.phone_toggle.toggle()

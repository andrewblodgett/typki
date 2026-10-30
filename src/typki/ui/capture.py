from collections.abc import Callable, Sequence
from dataclasses import replace

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
from typki.domain.template import BUILT_IN_TEMPLATES, Template, find_template
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
        self.applied_template: Template = find_template("blank")
        self.render_in_flight = False
        self.render_pending = False
        self.save_in_flight = False
        self.restoring = False

        self.deck_combo = QComboBox()
        self.deck_combo.setEditable(True)
        self.deck_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.deck_combo.setMinimumWidth(220)
        self.template_combo = QComboBox()
        for template in BUILT_IN_TEMPLATES:
            self.template_combo.addItem(template.title, template.key)
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("space-separated tags")
        self.mode_label = QLabel()
        self.mode_label.setTextFormat(Qt.TextFormat.PlainText)

        self.front_editor = TypstEditor()
        self.back_editor = TypstEditor()
        self.front_editor.setPlaceholderText("Front (Typst)")
        self.back_editor.setPlaceholderText("Back (Typst)")
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

    def set_shortcut_hints(self, shortcuts: dict[str, str]) -> None:
        self.save_next_button.setText(f"Save and next ({shortcuts['save_and_next']})")
        self.save_stay_button.setText(f"Save and stay ({shortcuts['save_and_stay']})")
        self.new_card_button.setText(f"New card ({shortcuts['new_card']})")

    def deck_name(self) -> str:
        return self.deck_combo.currentText().strip() or DEFAULT_DECK

    def template_key(self) -> str:
        return str(self.template_combo.currentData())

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
        return (
            self.front_editor.toPlainText() == self.applied_template.front
            and self.back_editor.toPlainText() == self.applied_template.back
        )

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
            self.apply_deck_defaults()
            self.apply_template(self.template_key())
        else:
            self.deck_combo.setCurrentText(draft.deck_name)
            self.select_template_key(draft.template_name)
            self.applied_template = find_template(draft.template_name)
            self.tags_edit.setText(" ".join(draft.tags))
            self.front_editor.setPlainText(draft.front)
            self.back_editor.setPlainText(draft.back)
            self.source_id = draft.source_id
            self.note_id = draft.note_id
        self.restoring = False
        self.update_mode_label()
        self.request_render()

    def select_template_key(self, key: str) -> None:
        index = self.template_combo.findData(find_template(key).key)
        self.template_combo.setCurrentIndex(max(index, 0))

    def apply_template(self, key: str) -> None:
        template = find_template(key)
        self.select_template_key(template.key)
        self.applied_template = template
        self.back_editor.setPlainText(template.back)
        self.front_editor.set_source(template.front)
        self.front_editor.setFocus()

    def apply_deck_defaults(self) -> None:
        config = self.service.library.resolve_deck(self.deck_name()).config
        self.select_template_key(config.default_template)
        if config.default_tags and not self.tags_edit.text().strip():
            self.tags_edit.setText(" ".join(config.default_tags))

    def on_template_chosen(self, _index: int) -> None:
        if not self.is_pristine():
            answer = QMessageBox.question(
                self,
                "Replace card text?",
                "Switching templates replaces the front and back you have typed.",
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Ok:
                self.select_template_key(self.applied_template.key)
                return
        self.apply_template(self.template_key())

    def on_deck_changed(self, _text: str) -> None:
        if self.restoring:
            return
        if self.note_id is None and self.is_pristine():
            self.apply_deck_defaults()
            self.apply_template(self.template_key())
        self.on_form_changed()
        self.render_timer.start()

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
        deck_name = self.deck_name()
        front = self.front_editor.toPlainText()
        back = self.back_editor.toPlainText()
        self.render_runner.run(
            lambda: self.service.render(deck_name, front, back),
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
        self.preview.show_sizes(card_render.front.byte_size, card_render.back.byte_size)
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
            self.status_message.emit("The front is empty, so there is nothing to save.")
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
        verb = "Added" if result.created else "Updated"
        self.status_message.emit(f"{verb} note {result.note_id} in {draft.deck_name}.")
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
            self.status_message.emit("Not saved: the card has compile errors.")
        elif isinstance(error, DuplicateNoteError):
            self.status_message.emit("Not saved: a Typki card with the same front already exists.")
        elif isinstance(error, AnkiUnavailableError):
            self.status_message.emit("Not saved: Anki is not reachable. The card stays in the form.")
        else:
            QMessageBox.warning(self, "Save failed", str(error))

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
                "Discard card?",
                "The current card has not been saved. Discard it?",
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
        self.applied_template = replace(
            find_template("blank"), front=card.front_source, back=card.back_source
        )
        self.select_template_key("blank")
        self.front_editor.setPlainText(card.front_source)
        self.back_editor.setPlainText(card.back_source)
        self.restoring = False
        self.update_mode_label(stale=opened.stale)
        self.save_draft()
        self.request_render()
        self.front_editor.setFocus()

    def update_mode_label(self, stale: bool = False) -> None:
        if self.note_id is None:
            self.mode_label.setText("New card")
            return
        suffix = " · stale, saving re-renders it" if stale else ""
        self.mode_label.setText(f"Editing note {self.note_id}{suffix}")

    def focus_front(self) -> None:
        self.front_editor.setFocus()

    def focus_back(self) -> None:
        self.back_editor.setFocus()

    def toggle_dark(self) -> None:
        self.preview.dark_toggle.toggle()

    def toggle_phone(self) -> None:
        self.preview.phone_toggle.toggle()

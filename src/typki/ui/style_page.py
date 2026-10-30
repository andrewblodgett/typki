from dataclasses import dataclass, replace

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from typki.anki.search import deck_with_children_term
from typki.card_service import CardRender, CardService, SearchResult
from typki.domain.card import parse_tags
from typki.domain.deck import DEFAULT_PAGE_WIDTH, DeckConfig, format_mm, length_to_mm
from typki.domain.template import BUILT_IN_TEMPLATES, find_template
from typki.library.store import DECK_MACROS_FILENAME, DECK_STYLE_FILENAME
from typki.render.diagnostics import Diagnostic
from typki.rerender.plan import StalenessReport
from typki.rerender.runner import Rerenderer
from typki.ui.background import TaskRunner
from typki.ui.editor import TypstEditor
from typki.ui.preview import CardPreview

WRITE_DEBOUNCE_MS = 250
STALENESS_DEBOUNCE_MS = 900
SAMPLE_LIMIT = 12
DEFAULT_DECK = "Default"
DIAGNOSTIC_ROLE = Qt.ItemDataRole.UserRole
SETTINGS_TAB = 0
DECK_MACROS_TAB = 1
DECK_STYLE_TAB = 2
GLOBAL_MACROS_TAB = 3

BUILT_IN_SAMPLE_FRONT = "*Define* a compact set $K subset RR$."
BUILT_IN_SAMPLE_BACK = """$K$ is *compact* if every open cover of $K$ has a finite subcover:
$ K subset.eq union.big_(i in I) U_i ==> K subset.eq U_(i_1) union dots.c union U_(i_n) $"""

DECK_MACROS_HINT = (
    "Functions and shortcuts for every card in this deck, e.g. #let defn(term, body) = [*#term.* #body]"
)
DECK_STYLE_HINT = "Define card-style(body) to set fonts, sizes, and colors for every card in this deck."
GLOBAL_MACROS_HINT = "Functions and shortcuts available on every card in every deck."


@dataclass(frozen=True)
class SampleCard:
    title: str
    front: str
    back: str


BUILT_IN_SAMPLE = SampleCard("Typki sample card", BUILT_IN_SAMPLE_FRONT, BUILT_IN_SAMPLE_BACK)


class StylePage(QWidget):
    status_message = Signal(str)
    rerender_requested = Signal(object)

    def __init__(
        self,
        service: CardService,
        render_runner: TaskRunner,
        anki_runner: TaskRunner,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.rerenderer = Rerenderer(service)
        self.render_runner = render_runner
        self.anki_runner = anki_runner
        self.current_deck = DEFAULT_DECK
        self.config = DeckConfig(anki_deck=DEFAULT_DECK)
        self.samples: list[SampleCard] = [BUILT_IN_SAMPLE]
        self.sample_index = 0
        self.loading = False
        self.initialized = False
        self.render_in_flight = False
        self.render_pending = False
        self.pending_writes: dict[str, str] = {}

        self.deck_combo = QComboBox()
        self.deck_combo.setEditable(True)
        self.deck_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.deck_combo.setMinimumWidth(240)
        self.ownership_label = QLabel()
        self.ownership_label.setWordWrap(True)
        self.own_style_button = QPushButton("Give this deck its own style")
        self.open_folder_button = QPushButton("Open folder")

        self.width_spin = QDoubleSpinBox()
        self.width_spin.setRange(30, 300)
        self.width_spin.setDecimals(0)
        self.width_spin.setSuffix(" mm")
        self.width_custom_label = QLabel()
        self.fit_check = QCheckBox("Shrink short cards to fit their content")
        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setRange(0.5, 4.0)
        self.scale_spin.setSingleStep(0.1)
        self.scale_spin.setDecimals(2)
        self.scale_spin.setSuffix(" ×")
        self.template_combo = QComboBox()
        for template in BUILT_IN_TEMPLATES:
            self.template_combo.addItem(template.title, template.key)
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("tags added to new cards, space-separated")

        self.deck_macros_editor = TypstEditor()
        self.deck_style_editor = TypstEditor()
        self.global_macros_editor = TypstEditor()
        self.editor_tabs = QTabWidget()
        self.diagnostics_list = QListWidget()
        self.diagnostics_list.setMaximumHeight(100)
        self.diagnostics_list.setVisible(False)

        self.preview = CardPreview()
        self.sample_label = QLabel()
        self.previous_sample_button = QPushButton("◀")
        self.next_sample_button = QPushButton("▶")
        for button in (self.previous_sample_button, self.next_sample_button):
            button.setFixedWidth(36)

        self.stale_label = QLabel()
        self.rerender_button = QPushButton("Re-render deck…")
        self.rerender_all_button = QPushButton("Re-render all decks…")

        self.build_layout()

        self.write_timer = QTimer(self, singleShot=True, interval=WRITE_DEBOUNCE_MS)
        self.write_timer.timeout.connect(self.flush_writes)
        self.staleness_timer = QTimer(self, singleShot=True, interval=STALENESS_DEBOUNCE_MS)
        self.staleness_timer.timeout.connect(self.refresh_staleness)

        self.deck_combo.currentTextChanged.connect(self.on_deck_text_changed)
        self.deck_combo.activated.connect(lambda _index: self.select_deck(self.deck_combo.currentText()))
        deck_line_edit = self.deck_combo.lineEdit()
        assert deck_line_edit is not None
        deck_line_edit.editingFinished.connect(lambda: self.select_deck(self.deck_combo.currentText()))
        self.own_style_button.clicked.connect(self.give_own_style)
        self.open_folder_button.clicked.connect(self.open_folder)
        self.width_spin.valueChanged.connect(self.on_settings_changed)
        self.fit_check.toggled.connect(self.on_settings_changed)
        self.scale_spin.valueChanged.connect(self.on_settings_changed)
        self.template_combo.currentIndexChanged.connect(self.on_settings_changed)
        self.tags_edit.textChanged.connect(self.on_settings_changed)
        self.deck_macros_editor.textChanged.connect(lambda: self.on_file_edited(DECK_MACROS_FILENAME))
        self.deck_style_editor.textChanged.connect(lambda: self.on_file_edited(DECK_STYLE_FILENAME))
        self.global_macros_editor.textChanged.connect(lambda: self.on_file_edited("global"))
        self.previous_sample_button.clicked.connect(lambda: self.step_sample(-1))
        self.next_sample_button.clicked.connect(lambda: self.step_sample(1))
        self.diagnostics_list.itemActivated.connect(self.on_diagnostic_activated)
        self.diagnostics_list.itemClicked.connect(self.on_diagnostic_activated)
        self.rerender_button.clicked.connect(lambda: self.rerender_requested.emit(self.current_deck))
        self.rerender_all_button.clicked.connect(lambda: self.rerender_requested.emit(None))

    def build_layout(self) -> None:
        deck_row = QHBoxLayout()
        deck_row.addWidget(QLabel("Deck"))
        deck_row.addWidget(self.deck_combo)
        deck_row.addWidget(self.ownership_label, 1)
        deck_row.addWidget(self.own_style_button)
        deck_row.addWidget(self.open_folder_button)

        settings = QWidget()
        form = QFormLayout(settings)
        width_row = QHBoxLayout()
        width_row.addWidget(self.width_spin)
        width_row.addWidget(self.width_custom_label, 1)
        form.addRow("Card width", width_row)
        form.addRow("", self.fit_check)
        form.addRow("Scale in Anki", self.scale_spin)
        form.addRow("Default template", self.template_combo)
        form.addRow("Default tags", self.tags_edit)
        explanation = QLabel(
            "Card width is the widest a card gets before text wraps. On phones, cards wider than "
            "the screen shrink to fit, so narrower cards keep text larger."
        )
        explanation.setWordWrap(True)
        explanation.setEnabled(False)
        form.addRow("", explanation)

        self.editor_tabs.addTab(settings, "Settings")
        self.editor_tabs.addTab(self.editor_page(self.deck_macros_editor, DECK_MACROS_HINT), "Deck macros")
        self.editor_tabs.addTab(self.editor_page(self.deck_style_editor, DECK_STYLE_HINT), "Deck style")
        self.editor_tabs.addTab(
            self.editor_page(self.global_macros_editor, GLOBAL_MACROS_HINT), "Global macros"
        )

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.editor_tabs, 1)
        left_layout.addWidget(self.diagnostics_list)

        sample_row = QHBoxLayout()
        sample_row.addWidget(self.previous_sample_button)
        sample_row.addWidget(self.sample_label, 1)
        sample_row.addWidget(self.next_sample_button)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addLayout(sample_row)
        right_layout.addWidget(self.preview, 1)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

        bottom = QHBoxLayout()
        bottom.addWidget(self.stale_label, 1)
        bottom.addWidget(self.rerender_all_button)
        bottom.addWidget(self.rerender_button)

        layout = QVBoxLayout(self)
        layout.addLayout(deck_row)
        layout.addWidget(splitter, 1)
        layout.addLayout(bottom)

    def editor_page(self, editor: TypstEditor, hint: str) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(4, 4, 4, 4)
        hint_label = QLabel(hint)
        hint_label.setWordWrap(True)
        hint_label.setEnabled(False)
        hint_label.setTextFormat(Qt.TextFormat.PlainText)
        page_layout.addWidget(hint_label)
        page_layout.addWidget(editor, 1)
        return page

    def set_deck_names(self, deck_names: list[str]) -> None:
        current = self.deck_combo.currentText() or self.current_deck
        self.deck_combo.blockSignals(True)
        self.deck_combo.clear()
        self.deck_combo.addItems(sorted(set(deck_names) | {current}))
        self.deck_combo.setCurrentText(current)
        self.deck_combo.blockSignals(False)

    def on_deck_text_changed(self, text: str) -> None:
        if self.deck_combo.findText(text) >= 0:
            self.select_deck(text)

    def select_deck(self, deck_name: str) -> None:
        deck_name = deck_name.strip() or DEFAULT_DECK
        if deck_name == self.current_deck and self.initialized:
            return
        self.flush_writes()
        self.initialized = True
        self.current_deck = deck_name
        self.deck_combo.setCurrentText(deck_name)
        self.reload_from_disk()
        self.load_samples()
        self.refresh_staleness()

    def show_deck(self, deck_name: str) -> None:
        if deck_name != self.current_deck or not self.initialized:
            self.initialized = False
            self.select_deck(deck_name)

    def owns_style(self) -> bool:
        return self.config.folder is not None and self.config.anki_deck == self.current_deck

    def reload_from_disk(self) -> None:
        library = self.service.library
        self.config = library.resolve_deck(self.current_deck).config
        self.loading = True
        self.load_settings_form(self.config)
        if self.config.folder is not None:
            folder = self.config.folder
            self.set_editor_text(
                self.deck_macros_editor,
                library.read_text(library.deck_file_path(folder, DECK_MACROS_FILENAME)),
            )
            self.set_editor_text(
                self.deck_style_editor, library.read_text(library.deck_file_path(folder, DECK_STYLE_FILENAME))
            )
        else:
            self.set_editor_text(self.deck_macros_editor, "")
            self.set_editor_text(self.deck_style_editor, "")
        self.set_editor_text(self.global_macros_editor, library.read_text(library.global_macros_path()))
        self.loading = False
        self.update_ownership_label()
        self.request_render()

    def set_editor_text(self, editor: TypstEditor, text: str) -> None:
        if editor.toPlainText() != text:
            editor.setPlainText(text)

    def load_settings_form(self, config: DeckConfig) -> None:
        millimetres = length_to_mm(config.page_width)
        if millimetres is None:
            self.width_spin.setEnabled(False)
            self.width_custom_label.setText(f"{config.page_width} (set in deck.toml)")
            millimetres = length_to_mm(DEFAULT_PAGE_WIDTH) or 80
        else:
            self.width_spin.setEnabled(True)
            self.width_custom_label.clear()
        self.width_spin.setValue(millimetres)
        self.fit_check.setChecked(config.fit_width)
        self.scale_spin.setValue(config.scale)
        self.template_combo.setCurrentIndex(
            max(self.template_combo.findData(find_template(config.default_template).key), 0)
        )
        self.tags_edit.setText(" ".join(config.default_tags))

    def update_ownership_label(self) -> None:
        if self.owns_style():
            self.ownership_label.setText(f"Style saved in decks/{self.config.folder}/")
            self.own_style_button.setVisible(False)
        elif self.config.folder is not None:
            self.ownership_label.setText(
                f"Uses the style of “{self.config.anki_deck}”. "
                "Changes here apply to that deck and all its subdecks."
            )
            self.own_style_button.setVisible(True)
        else:
            self.ownership_label.setText(
                "Uses Typki's default style. Changing anything gives this deck its own style."
            )
            self.own_style_button.setVisible(False)
        self.open_folder_button.setVisible(self.config.folder is not None)

    def ensure_deck_folder(self) -> str:
        if self.config.folder is None:
            self.config = self.service.library.create_deck_folder(self.current_deck)
            self.update_ownership_label()
            self.status_message.emit(f"Created decks/{self.config.folder}/ for “{self.current_deck}”.")
        assert self.config.folder is not None
        return self.config.folder

    def give_own_style(self) -> None:
        self.flush_writes()
        self.config = self.service.library.create_deck_folder(self.current_deck)
        self.status_message.emit(
            f"“{self.current_deck}” now has its own style in decks/{self.config.folder}/."
        )
        self.reload_from_disk()
        self.refresh_staleness()

    def open_folder(self) -> None:
        if self.config.folder is not None:
            path = self.service.library.deck_folder_path(self.config.folder)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def settings_from_form(self) -> DeckConfig:
        page_width = (
            format_mm(self.width_spin.value()) if self.width_spin.isEnabled() else self.config.page_width
        )
        return replace(
            self.config,
            page_width=page_width,
            fit_width=self.fit_check.isChecked(),
            scale=round(self.scale_spin.value(), 2),
            default_template=str(self.template_combo.currentData()),
            default_tags=parse_tags(self.tags_edit.text()),
        )

    def on_settings_changed(self) -> None:
        if self.loading:
            return
        self.pending_writes["deck.toml"] = ""
        self.write_timer.start()

    def on_file_edited(self, which: str) -> None:
        if self.loading:
            return
        editors = {
            DECK_MACROS_FILENAME: self.deck_macros_editor,
            DECK_STYLE_FILENAME: self.deck_style_editor,
            "global": self.global_macros_editor,
        }
        self.pending_writes[which] = editors[which].toPlainText()
        self.write_timer.start()

    def flush_writes(self) -> None:
        if not self.pending_writes:
            return
        writes, self.pending_writes = self.pending_writes, {}
        library = self.service.library
        for which, text in writes.items():
            if which == "global":
                library.write_text(library.global_macros_path(), text)
                continue
            if which == "deck.toml":
                folder = self.ensure_deck_folder()
                self.config = replace(self.settings_from_form(), folder=folder)
                library.write_deck_settings(self.config)
                continue
            folder = self.ensure_deck_folder()
            library.write_text(library.deck_file_path(folder, which), text)
        self.request_render()
        self.staleness_timer.start()

    def on_library_changed(self) -> None:
        if not self.initialized or self.pending_writes:
            return
        focused = QApplication.focusWidget()
        user_is_typing_here = self.isActiveWindow() and focused is not None and self.isAncestorOf(focused)
        if user_is_typing_here:
            self.request_render()
        else:
            self.reload_from_disk()
        self.staleness_timer.start()

    def load_samples(self) -> None:
        deck_name = self.current_deck
        query = deck_with_children_term(deck_name)
        self.anki_runner.run(
            lambda: self.service.search(query, limit=SAMPLE_LIMIT),
            lambda result: self.on_samples(deck_name, result),
            lambda _error: self.on_samples(deck_name, None),
        )

    def on_samples(self, deck_name: str, result: SearchResult | None) -> None:
        if deck_name != self.current_deck:
            return
        samples = [
            SampleCard(
                f"Card from {summary.card.deck_name}", summary.card.front_source, summary.card.back_source
            )
            for summary in (result.cards if result else ())
        ]
        self.samples = samples or [BUILT_IN_SAMPLE]
        self.sample_index = 0
        self.request_render()

    def step_sample(self, step: int) -> None:
        self.sample_index = (self.sample_index + step) % len(self.samples)
        self.request_render()

    def request_render(self) -> None:
        if self.render_in_flight:
            self.render_pending = True
            return
        sample = self.samples[self.sample_index % len(self.samples)]
        count = len(self.samples)
        position = f"{self.sample_index % count + 1} of {count}" if count > 1 else ""
        self.sample_label.setText(f"{sample.title} {position}".strip())
        self.previous_sample_button.setEnabled(count > 1)
        self.next_sample_button.setEnabled(count > 1)
        self.render_in_flight = True
        deck_name = self.current_deck
        self.render_runner.run(
            lambda: self.service.render(deck_name, sample.front, sample.back),
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
        self.preview.set_side("front", card_render.front.svg, not card_render.front.ok)
        self.preview.set_side("back", card_render.back.svg, not card_render.back.ok)
        self.preview.show_sizes(card_render.front.byte_size, card_render.back.byte_size)
        diagnostics = list(card_render.front.diagnostics) + [
            diagnostic
            for diagnostic in card_render.back.diagnostics
            if diagnostic not in card_render.front.diagnostics
        ]
        self.show_diagnostics(diagnostics)

    def on_render_crashed(self, error: Exception) -> None:
        if self.finish_render_cycle():
            self.show_diagnostics([Diagnostic("error", str(error))])

    def show_diagnostics(self, diagnostics: list[Diagnostic]) -> None:
        self.diagnostics_list.clear()
        files = self.file_editors()
        for editor in files.values():
            editor.show_diagnostics([])
        for diagnostic in diagnostics:
            label = diagnostic.describe() if diagnostic.file else f"sample card: {diagnostic.describe()}"
            item = QListWidgetItem(label)
            item.setData(DIAGNOSTIC_ROLE, diagnostic)
            if diagnostic.hints:
                item.setToolTip("\n".join(diagnostic.hints))
            item.setForeground(
                Qt.GlobalColor.red if diagnostic.severity == "error" else Qt.GlobalColor.darkYellow
            )
            self.diagnostics_list.addItem(item)
            matching_editor = files.get(diagnostic.file or "")
            if matching_editor is not None and diagnostic.line is not None:
                matching_editor.show_diagnostics([replace(diagnostic, file=None)])
        self.diagnostics_list.setVisible(bool(diagnostics))

    def file_editors(self) -> dict[str, TypstEditor]:
        editors = {"global/macros.typ": self.global_macros_editor}
        if self.config.folder is not None:
            prefix = f"decks/{self.config.folder}/"
            editors[prefix + DECK_MACROS_FILENAME] = self.deck_macros_editor
            editors[prefix + DECK_STYLE_FILENAME] = self.deck_style_editor
        return editors

    def on_diagnostic_activated(self, item: QListWidgetItem) -> None:
        self.reveal_diagnostic(item.data(DIAGNOSTIC_ROLE))

    def reveal_diagnostic(self, diagnostic: Diagnostic) -> None:
        editor = self.file_editors().get(diagnostic.file or "")
        if editor is None or diagnostic.line is None:
            return
        tab_for_editor = {
            id(self.deck_macros_editor): DECK_MACROS_TAB,
            id(self.deck_style_editor): DECK_STYLE_TAB,
            id(self.global_macros_editor): GLOBAL_MACROS_TAB,
        }
        self.editor_tabs.setCurrentIndex(tab_for_editor[id(editor)])
        editor.jump_to(diagnostic.line, diagnostic.column or 1)

    def refresh_staleness(self) -> None:
        deck_name = self.current_deck
        self.anki_runner.run(
            lambda: (self.rerenderer.staleness(deck_name), self.rerenderer.staleness(None)),
            lambda reports: self.on_staleness(deck_name, reports),
            lambda _error: self.stale_label.setText(
                "Anki is not reachable, so stale cards cannot be counted."
            ),
        )

    def on_staleness(self, deck_name: str, reports: tuple[StalenessReport, StalenessReport]) -> None:
        if deck_name != self.current_deck:
            return
        deck_report, all_report = reports
        if deck_report.total == 0:
            deck_text = f"“{deck_name}” has no Typki cards yet."
        elif deck_report.stale_count == 0:
            deck_text = f"All {deck_report.total} cards in “{deck_name}” are up to date."
        else:
            deck_text = (
                f"{deck_report.stale_count} of {deck_report.total} cards in “{deck_name}” use an older style "
                "and need re-rendering."
            )
        other_stale = all_report.stale_count - deck_report.stale_count
        if other_stale > 0:
            deck_text += f" {other_stale} more in other decks."
        self.stale_label.setText(deck_text)
        self.rerender_button.setEnabled(deck_report.stale_count > 0)
        self.rerender_all_button.setEnabled(all_report.stale_count > 0)

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

from conftest import replace_defn
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QListWidgetItem
from pytestqt.qtbot import QtBot

from typki.anki import note_type
from typki.anki.ankiconnect import AnkiConnectGateway
from typki.anki.fake_anki import FakeAnki
from typki.card_service import CardService
from typki.domain.card import CardDraft
from typki.library.drafts import DraftStore
from typki.library.outbox import Outbox
from typki.ui.background import TaskRunner
from typki.ui.browser import BrowserPage
from typki.ui.capture import CapturePage
from typki.ui.global_page import GlobalPage
from typki.ui.main_window import MainWindow
from typki.ui.save_queue import SaveQueue
from typki.ui.setup_page import INSTALL_STEPS, UPDATE_STEPS
from typki.ui.shortcuts import SHORTCUT_ACTIONS
from typki.ui.theme import find_theme

WAIT_MS = 10000
DEAD_URL = "http://127.0.0.1:9"


def raise_error(error: Exception) -> None:
    raise error


def build_window(
    service: CardService, gateway: AnkiConnectGateway, state_dir: Path, show_setup: bool = False
) -> MainWindow:
    render_runner = TaskRunner(1, raise_error)
    anki_runner = TaskRunner(2, raise_error)
    save_queue = SaveQueue(service, anki_runner, Outbox(state_dir / "outbox"))
    capture = CapturePage(service, render_runner, save_queue, DraftStore(state_dir / "draft.json"))
    browser = BrowserPage(service, anki_runner)
    global_page = GlobalPage(service, render_runner)
    shortcuts = {action.key: action.default for action in SHORTCUT_ACTIONS}
    return MainWindow(
        gateway,
        service,
        capture,
        browser,
        global_page,
        save_queue,
        anki_runner,
        render_runner,
        shortcuts,
        [],
        show_setup,
    )


def settle(window: MainWindow) -> None:
    for _ in range(3):
        window.anki_runner.wait()
        window.render_runner.wait()
        QApplication.processEvents()


@pytest.fixture
def window(
    qtbot: QtBot,
    service: CardService,
    fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki],
    tmp_path: Path,
) -> Iterator[MainWindow]:
    gateway, _ = fake_ankiconnect
    main_window = build_window(service, gateway, tmp_path / "state")
    qtbot.addWidget(main_window)
    main_window.capture.restore(None)
    main_window.show()
    qtbot.waitUntil(lambda: main_window.anki_connected, timeout=WAIT_MS)
    yield main_window
    settle(main_window)


def type_card(window: MainWindow, deck: str, front: str, back: str = "") -> None:
    capture = window.capture
    capture.deck_combo.setCurrentText(deck)
    capture.front_editor.setPlainText(front)
    capture.back_editor.setPlainText(back)


def note_with_front(fake: FakeAnki, front: str) -> list[int]:
    return [note_id for note_id, note in fake.notes.items() if note.fields[note_type.FRONT_SOURCE] == front]


def test_typing_autosaves_and_shows_saved(
    qtbot: QtBot, window: MainWindow, fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki]
) -> None:
    _, fake = fake_ankiconnect
    type_card(window, "Real Analysis", "*Define* a Cauchy sequence.", "$ forall epsilon > 0 $")
    qtbot.waitUntil(lambda: len(fake.notes) == 1, timeout=WAIT_MS)
    qtbot.waitUntil(lambda: window.indicator.text() == "Saved", timeout=WAIT_MS)
    stored = next(iter(fake.notes.values()))
    assert stored.deck_name == "Real Analysis"
    assert stored.fields[note_type.BACK_SOURCE] == "$ forall epsilon > 0 $"


def test_further_edits_update_the_same_note(
    qtbot: QtBot, window: MainWindow, fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki]
) -> None:
    _, fake = fake_ankiconnect
    type_card(window, "Real Analysis", "Heine Borel", "closed and bounded")
    qtbot.waitUntil(lambda: len(fake.notes) == 1, timeout=WAIT_MS)
    window.capture.back_editor.setPlainText("closed and bounded iff compact")
    window.capture.tags_edit.setText("topology")
    qtbot.waitUntil(
        lambda: (
            next(iter(fake.notes.values())).fields[note_type.BACK_SOURCE] == "closed and bounded iff compact"
        ),
        timeout=WAIT_MS,
    )
    qtbot.waitUntil(lambda: next(iter(fake.notes.values())).tags == ["topology"], timeout=WAIT_MS)
    assert len(fake.notes) == 1


def test_compile_error_is_not_saved(
    qtbot: QtBot, window: MainWindow, fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki]
) -> None:
    _, fake = fake_ankiconnect
    type_card(window, "Real Analysis", "fine\n$ nosuchthing(x) $", "back")
    qtbot.waitUntil(lambda: window.capture.diagnostics_list.count() > 0, timeout=WAIT_MS)
    assert "Front card:2:" in window.capture.diagnostics_list.item(0).text()
    qtbot.wait(800)
    assert not fake.notes


def test_template_starts_new_card_and_placeholders_block_saving(
    qtbot: QtBot, window: MainWindow, fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki]
) -> None:
    _, fake = fake_ankiconnect
    capture = window.capture
    type_card(window, "Real Analysis", "first card")
    capture.template_combo.setCurrentIndex(capture.template_combo.findData("theorem"))
    capture.template_combo.activated.emit(capture.template_combo.currentIndex())
    qtbot.waitUntil(lambda: len(note_with_front(fake, "first card")) == 1, timeout=WAIT_MS)
    assert capture.front_editor.toPlainText() == "#theorem[«name»][«statement»]"
    assert capture.front_editor.textCursor().selectedText() == "«name»"
    assert capture.back_editor.toPlainText() == ""
    assert capture.tags_edit.text().split()[-1] == "theorem"
    qtbot.wait(800)
    assert len(fake.notes) == 1
    capture.front_editor.setPlainText("#theorem[Rolle][$f(a) = f(b) ==> exists c : f'(c) = 0$]")
    qtbot.waitUntil(lambda: len(fake.notes) == 2, timeout=WAIT_MS)
    newest = fake.notes[max(fake.notes)]
    assert "theorem" in newest.tags


def test_new_card_shortcut_saves_immediately_and_resets(
    qtbot: QtBot, window: MainWindow, fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki]
) -> None:
    _, fake = fake_ankiconnect
    capture = window.capture
    type_card(window, "Real Analysis", "quick card", "answer")
    qtbot.waitUntil(lambda: capture.last_render_ok, timeout=WAIT_MS)
    first_source = capture.source_id
    qtbot.keyClick(capture.front_editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert capture.source_id != first_source
    assert capture.front_editor.toPlainText() == ""
    assert capture.deck_name() == "Real Analysis"
    qtbot.waitUntil(lambda: len(note_with_front(fake, "quick card")) == 1, timeout=WAIT_MS)


def test_save_and_new_button_saves_and_resets(
    qtbot: QtBot, window: MainWindow, fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki]
) -> None:
    _, fake = fake_ankiconnect
    capture = window.capture
    type_card(window, "Real Analysis", "button card", "answer")
    qtbot.waitUntil(lambda: capture.last_render_ok, timeout=WAIT_MS)
    first_source = capture.source_id
    qtbot.mouseClick(capture.save_new_button, Qt.MouseButton.LeftButton)
    assert capture.source_id != first_source
    assert capture.front_editor.toPlainText() == ""
    assert capture.save_new_button.toolTip()
    qtbot.waitUntil(lambda: len(note_with_front(fake, "button card")) == 1, timeout=WAIT_MS)


def test_clicking_deck_field_opens_deck_list(qtbot: QtBot, window: MainWindow) -> None:
    capture = window.capture
    capture.set_deck_names(["Default", "Physics"])
    qtbot.mouseClick(capture.deck_combo.lineEdit(), Qt.MouseButton.LeftButton)
    qtbot.waitUntil(capture.deck_combo.view().isVisible, timeout=WAIT_MS)
    assert capture.deck_combo.findText("Physics") >= 0
    capture.deck_combo.hidePopup()


def test_open_from_browse_and_edit_in_place(
    qtbot: QtBot, window: MainWindow, fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki]
) -> None:
    _, fake = fake_ankiconnect
    type_card(window, "Real Analysis", "Bolzano Weierstrass", "bounded sequences converge on a subsequence")
    qtbot.waitUntil(lambda: len(fake.notes) == 1, timeout=WAIT_MS)
    window.capture.new_card()
    window.focus_search()
    browser = window.browser
    qtbot.keyClicks(browser.search_edit, "Bolzano")
    qtbot.waitUntil(lambda: browser.results.count() == 1, timeout=WAIT_MS)
    assert not browser.results.item(0).icon().isNull()
    browser.results.itemActivated.emit(browser.results.item(0))
    qtbot.waitUntil(
        lambda: window.capture.front_editor.toPlainText() == "Bolzano Weierstrass", timeout=WAIT_MS
    )
    assert window.tabs.currentIndex() == 0
    window.capture.back_editor.setPlainText("every bounded sequence has a convergent subsequence")
    qtbot.waitUntil(
        lambda: next(iter(fake.notes.values())).fields[note_type.BACK_SOURCE].startswith("every bounded"),
        timeout=WAIT_MS,
    )
    assert len(fake.notes) == 1


def test_browse_lists_newest_first_and_filters_as_you_type(
    qtbot: QtBot,
    window: MainWindow,
    service: CardService,
    fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki],
) -> None:
    _, fake = fake_ankiconnect
    for front in ("alpha card", "beta card", "gamma card"):
        service.save(CardDraft("Real Analysis", "", (), front, ""))
    window.tabs.setCurrentIndex(1)
    browser = window.browser
    qtbot.waitUntil(lambda: browser.results.count() == 3, timeout=WAIT_MS)
    assert browser.results.item(0).data(Qt.ItemDataRole.UserRole) == max(fake.notes)
    qtbot.keyClicks(browser.search_edit, "beta")
    qtbot.waitUntil(lambda: browser.results.count() == 1, timeout=WAIT_MS)


def test_browse_loads_more_on_scroll(qtbot: QtBot, window: MainWindow, service: CardService) -> None:
    for index in range(95):
        service.save(CardDraft("Real Analysis", "", (), f"card number {index}", ""))
    window.tabs.setCurrentIndex(1)
    browser = window.browser
    qtbot.waitUntil(lambda: browser.results.count() >= 40, timeout=WAIT_MS)
    browser.results.scrollToBottom()
    qtbot.waitUntil(lambda: browser.results.count() >= 80, timeout=WAIT_MS)
    browser.results.scrollToBottom()
    qtbot.waitUntil(lambda: browser.results.count() == 95, timeout=WAIT_MS)


def select_card(window: MainWindow, note_id: int) -> QListWidgetItem:
    results = window.browser.results
    results.setFocus()
    item = next(
        results.item(index)
        for index in range(results.count())
        if results.item(index).data(Qt.ItemDataRole.UserRole) == note_id
    )
    results.setCurrentItem(item)
    return item


@pytest.mark.parametrize(
    "modifier", [Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ControlModifier], ids=["del", "ctrl-del"]
)
def test_delete_key_removes_selected_card(
    qtbot: QtBot,
    window: MainWindow,
    service: CardService,
    fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki],
    modifier: Qt.KeyboardModifier,
) -> None:
    _, fake = fake_ankiconnect
    doomed = service.save(CardDraft("Real Analysis", "", (), "delete me", "")).note_id
    service.save(CardDraft("Real Analysis", "", (), "keep me", ""))
    window.tabs.setCurrentIndex(1)
    browser = window.browser
    qtbot.waitUntil(lambda: browser.results.count() == 2, timeout=WAIT_MS)
    select_card(window, doomed)
    qtbot.keyClick(browser.results, Qt.Key.Key_Delete, modifier)
    qtbot.waitUntil(lambda: doomed not in fake.notes, timeout=WAIT_MS)
    qtbot.waitUntil(lambda: browser.results.count() == 1, timeout=WAIT_MS)
    assert len(fake.notes) == 1


def test_right_click_menu_deletes_card(
    qtbot: QtBot,
    window: MainWindow,
    service: CardService,
    fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki],
) -> None:
    _, fake = fake_ankiconnect
    doomed = service.save(CardDraft("Real Analysis", "", (), "delete me", "")).note_id
    window.tabs.setCurrentIndex(1)
    qtbot.waitUntil(lambda: window.browser.results.count() == 1, timeout=WAIT_MS)
    menu = window.browser.card_menu_for(select_card(window, doomed))
    assert [action.text() for action in menu.actions()] == ["Open", "Delete"]
    menu.actions()[1].trigger()
    qtbot.waitUntil(lambda: doomed not in fake.notes, timeout=WAIT_MS)


def test_leaving_global_tab_rerenders_in_background(
    qtbot: QtBot,
    window: MainWindow,
    service: CardService,
    fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki],
) -> None:
    _, fake = fake_ankiconnect
    for index in range(30):
        service.save(CardDraft("Real Analysis", "", (), f"#defn[Term {index}][meaning]", ""))
    reviewed = next(iter(fake.notes))
    fake.notes[reviewed].review_count = 4
    window.tabs.setCurrentIndex(2)
    header = window.global_page.header_editor
    header.setFocus()
    header.setPlainText(header.toPlainText().replace("[*#term.* #body]", "[_#term:_ #body]"))
    window.tabs.setCurrentIndex(0)
    qtbot.waitUntil(lambda: window.rerender.rerenderer.staleness().stale_count == 0, timeout=WAIT_MS)
    assert fake.notes[reviewed].review_count == 4
    assert len(fake.notes) == 30


def test_broken_header_leaves_cards_untouched(
    qtbot: QtBot,
    window: MainWindow,
    service: CardService,
    fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki],
) -> None:
    _, fake = fake_ankiconnect
    for index in range(3):
        service.save(CardDraft("Real Analysis", "", (), f"#defn[Broken {index}][x]", ""))
    before = {note_id: dict(note.fields) for note_id, note in fake.notes.items()}
    replace_defn(service.library, "#let defn(term, body) = [#nope]")
    window.tabs.setCurrentIndex(2)
    window.tabs.setCurrentIndex(0)
    qtbot.waitUntil(lambda: window.rerender.failed == 3, timeout=WAIT_MS)
    assert "3 cards not re-rendered" in window.indicator.text()
    assert {note_id: note.fields for note_id, note in fake.notes.items()} == before


def test_offline_cards_sync_when_anki_returns_without_duplicates(
    qtbot: QtBot, window: MainWindow, fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki]
) -> None:
    gateway, fake = fake_ankiconnect
    live_url = gateway.url
    gateway.url = DEAD_URL
    capture = window.capture
    for index in range(3):
        type_card(window, "Real Analysis", f"offline card {index}", "back")
        qtbot.waitUntil(lambda: capture.last_render_ok, timeout=WAIT_MS)
        capture.new_card()
    qtbot.waitUntil(lambda: window.save_queue.outbox.count() == 3, timeout=WAIT_MS)
    qtbot.waitUntil(lambda: window.indicator.text().startswith("Offline · 3 queued"), timeout=WAIT_MS)
    assert not fake.notes
    gateway.url = live_url
    window.connect_to_anki()
    qtbot.waitUntil(lambda: len(fake.notes) == 3, timeout=WAIT_MS)
    qtbot.waitUntil(lambda: window.save_queue.outbox.count() == 0, timeout=WAIT_MS)
    window.connect_to_anki()
    settle(window)
    assert sorted(note.fields[note_type.FRONT_SOURCE] for note in fake.notes.values()) == [
        "offline card 0",
        "offline card 1",
        "offline card 2",
    ]


def test_outbox_survives_restart(
    qtbot: QtBot,
    service: CardService,
    fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki],
    tmp_path: Path,
) -> None:
    gateway, fake = fake_ankiconnect
    Outbox(tmp_path / "restart" / "outbox").put(
        CardDraft("Real Analysis", "", (), "queued before restart", "")
    )
    restarted = build_window(service, gateway, tmp_path / "restart")
    qtbot.addWidget(restarted)
    restarted.capture.restore(None)
    restarted.show()
    qtbot.waitUntil(lambda: len(fake.notes) == 1, timeout=WAIT_MS)
    settle(restarted)


def test_tag_completion_inserts_known_tag(qtbot: QtBot, window: MainWindow) -> None:
    tags_edit = window.capture.tags_edit
    tags_edit.set_known_tags(["real-analysis", "topology"])
    tags_edit.setFocus()
    qtbot.keyClicks(tags_edit, "algebra top")
    tags_edit.insert_completion("topology")
    assert tags_edit.text() == "algebra topology "


def test_global_tab_shows_and_saves_header(qtbot: QtBot, window: MainWindow, service: CardService) -> None:
    type_card(window, "Real Analysis", "#defn[Field][complete]", "back")
    window.tabs.setCurrentIndex(2)
    global_page = window.global_page
    assert "New Computer Modern" in global_page.header_editor.toPlainText()
    assert global_page.sample_front == "#defn[Field][complete]"
    global_page.header_editor.setFocus()
    global_page.header_editor.setPlainText(global_page.header_editor.toPlainText() + "#let shiny = [new]\n")
    qtbot.waitUntil(lambda: "#let shiny" in service.library.read_header(), timeout=WAIT_MS)
    qtbot.waitUntil(lambda: window.capture.template_combo.findData("shiny") < 0, timeout=WAIT_MS)


def test_header_functions_become_templates(qtbot: QtBot, window: MainWindow, service: CardService) -> None:
    lemma = "#let lemma(statement) = [*Lemma.* #statement]\n"
    service.library.write_header(service.library.read_header() + lemma)
    qtbot.waitUntil(lambda: window.capture.template_combo.findData("lemma") >= 0, timeout=WAIT_MS)


def test_header_error_is_listed_and_jumps_to_line(qtbot: QtBot, window: MainWindow) -> None:
    window.tabs.setCurrentIndex(2)
    global_page = window.global_page
    global_page.header_editor.setPlainText("#set text(size: 12pt)\n#let broken = (\n")
    qtbot.waitUntil(lambda: global_page.diagnostics_list.count() > 0, timeout=WAIT_MS)
    assert global_page.diagnostics_list.item(0).text().startswith("header.typ:2:")
    global_page.diagnostics_list.itemActivated.emit(global_page.diagnostics_list.item(0))
    assert global_page.header_editor.textCursor().blockNumber() == 1


def test_external_header_edit_reloads_global_tab(
    qtbot: QtBot, window: MainWindow, service: CardService
) -> None:
    window.tabs.setCurrentIndex(2)
    window.tabs.setFocus()
    service.library.write_header(service.library.read_header() + "#let external = 1\n")
    qtbot.waitUntil(
        lambda: "#let external" in window.global_page.header_editor.toPlainText(), timeout=WAIT_MS
    )


def test_draft_restores_after_restart(
    qtbot: QtBot,
    window: MainWindow,
    service: CardService,
    fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki],
) -> None:
    gateway, _ = fake_ankiconnect
    type_card(window, "Real Analysis", "unsaved thought", "half written")
    window.capture.save_draft()
    restored = window.capture.draft_store.load()
    assert restored is not None
    assert restored.front == "unsaved thought"
    assert restored.source_id == window.capture.source_id


def test_first_run_shows_setup_until_anki_answers(
    qtbot: QtBot, service: CardService, fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki], tmp_path: Path
) -> None:
    gateway, _ = fake_ankiconnect
    live_url = gateway.url
    gateway.url = DEAD_URL
    main_window = build_window(service, gateway, tmp_path / "state", show_setup=True)
    qtbot.addWidget(main_window)
    connections: list[bool] = []
    main_window.connected.connect(lambda: connections.append(True))
    main_window.capture.restore(None)
    main_window.show()
    qtbot.waitUntil(main_window.reconnect_timer.isActive, timeout=WAIT_MS)
    assert main_window.setup_visible
    assert main_window.setup_page.shown_steps == INSTALL_STEPS
    assert main_window.setup_page.code_row.isVisible()
    gateway.url = live_url
    qtbot.waitUntil(lambda: main_window.anki_connected, timeout=WAIT_MS)
    assert not main_window.setup_visible
    assert connections
    settle(main_window)


def test_setup_explains_outdated_ankiconnect_and_can_be_skipped(
    qtbot: QtBot,
    service: CardService,
    fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway, _ = fake_ankiconnect
    monkeypatch.setattr(gateway, "version", lambda: 5)
    main_window = build_window(service, gateway, tmp_path / "state", show_setup=True)
    qtbot.addWidget(main_window)
    main_window.capture.restore(None)
    main_window.show()
    qtbot.waitUntil(lambda: main_window.setup_page.shown_steps == UPDATE_STEPS, timeout=WAIT_MS)
    assert not main_window.setup_page.code_row.isVisible()
    qtbot.keyClick(main_window.setup_page, Qt.Key.Key_Escape)
    assert not main_window.setup_visible
    settle(main_window)


def test_setup_stays_hidden_when_anki_is_already_running(
    qtbot: QtBot, service: CardService, fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki], tmp_path: Path
) -> None:
    gateway, _ = fake_ankiconnect
    main_window = build_window(service, gateway, tmp_path / "state", show_setup=True)
    qtbot.addWidget(main_window)
    main_window.capture.restore(None)
    main_window.show()
    qtbot.waitUntil(lambda: main_window.anki_connected, timeout=WAIT_MS)
    assert not main_window.setup_visible
    assert not main_window.offer_setup
    settle(main_window)


def test_switching_theme_recolors_without_touching_sources(
    qtbot: QtBot, window: MainWindow, service: CardService
) -> None:
    header = service.library.read_header()
    window.capture.front_editor.setPlainText("$x$")
    qtbot.waitUntil(lambda: window.capture.last_render_ok, timeout=WAIT_MS)
    window.capture.flush()
    window.tabs.setCurrentIndex(2)
    emitted: list[str] = []
    window.theme_changed.connect(emitted.append)
    nord = find_theme("Nord")
    window.choose_theme(nord)
    assert emitted == ["Nord"]
    assert QApplication.palette().window().color().name() == nord.chrome
    assert [action.data() for action in window.theme_actions.actions() if action.isChecked()] == ["Nord"]
    assert not window.global_page.write_pending
    assert not window.capture.autosave_timer.isActive()
    assert service.library.read_header() == header


def test_typing_math_completes_functions_with_tab(qtbot: QtBot, window: MainWindow) -> None:
    editor = window.capture.front_editor
    editor.setFocus()
    qtbot.keyClicks(editor, "$fr")
    assert editor.toPlainText() == "$fr$"
    popup = editor.completion_popup
    qtbot.waitUntil(popup.is_visible, timeout=WAIT_MS)
    assert popup.view.currentIndex().data() == "frac"
    qtbot.keyClick(popup.view, Qt.Key.Key_Tab)
    assert editor.toPlainText() == "$frac()$"
    assert editor.textCursor().position() == len("$frac(")
    qtbot.keyClicks(editor, "a")
    qtbot.keyClick(editor, Qt.Key.Key_ParenRight)
    qtbot.keyClick(editor, Qt.Key.Key_Dollar)
    assert editor.toPlainText() == "$frac(a)$"
    assert editor.textCursor().position() == len("$frac(a)$")


def test_hash_completion_lists_header_macros(qtbot: QtBot, window: MainWindow) -> None:
    editor = window.capture.front_editor
    editor.setFocus()
    qtbot.keyClicks(editor, "#def")
    popup = editor.completion_popup
    qtbot.waitUntil(popup.is_visible, timeout=WAIT_MS)
    qtbot.keyClick(popup.view, Qt.Key.Key_Return)
    assert editor.toPlainText() == "#defn()"


def test_escape_closes_completion_without_inserting(qtbot: QtBot, window: MainWindow) -> None:
    editor = window.capture.front_editor
    editor.setFocus()
    qtbot.keyClicks(editor, "$al")
    popup = editor.completion_popup
    qtbot.waitUntil(popup.is_visible, timeout=WAIT_MS)
    qtbot.keyClick(popup.view, Qt.Key.Key_Escape)
    assert not popup.is_visible()
    assert editor.toPlainText() == "$al$"


def test_editor_line_shortcuts(qtbot: QtBot, window: MainWindow) -> None:
    editor = window.capture.front_editor
    editor.setFocus()
    editor.setPlainText("first\nsecond")
    qtbot.keyClick(editor, Qt.Key.Key_Slash, Qt.KeyboardModifier.ControlModifier)
    assert editor.toPlainText() == "// first\nsecond"
    qtbot.keyClick(editor, Qt.Key.Key_Slash, Qt.KeyboardModifier.ControlModifier)
    qtbot.keyClick(editor, Qt.Key.Key_Down, Qt.KeyboardModifier.AltModifier)
    assert editor.toPlainText() == "second\nfirst"
    qtbot.keyClick(editor, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert editor.toPlainText() == "first\nsecond"
    editor.moveCursor(QTextCursor.MoveOperation.Start)
    qtbot.keyClick(
        editor, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
    )
    assert editor.toPlainText() == "second"


def test_matching_bracket_is_highlighted(qtbot: QtBot, window: MainWindow) -> None:
    editor = window.capture.front_editor
    editor.setPlainText("#f(x)")
    cursor = editor.textCursor()
    cursor.setPosition(3)
    editor.setTextCursor(cursor)
    assert [selection.cursor.selectionStart() for selection in editor.bracket_selections] == [2, 4]

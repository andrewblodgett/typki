import os
from collections.abc import Iterator
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

from conftest import replace_defn
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox
from pytestqt.qtbot import QtBot

from typki.anki import note_type
from typki.anki.ankiconnect import AnkiConnectGateway
from typki.anki.fake_anki import FakeAnki
from typki.card_service import CardService
from typki.domain.card import CardDraft
from typki.library.drafts import DraftStore
from typki.ui.background import TaskRunner
from typki.ui.browser import BrowserPage
from typki.ui.capture import CapturePage
from typki.ui.global_page import GlobalPage
from typki.ui.main_window import MainWindow
from typki.ui.rerender_dialog import RerenderDialog
from typki.ui.shortcuts import SHORTCUT_ACTIONS

WAIT_MS = 10000


def raise_error(error: Exception) -> None:
    raise error


@pytest.fixture
def window(
    qtbot: QtBot,
    service: CardService,
    fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki],
    tmp_path: Path,
) -> Iterator[MainWindow]:
    gateway, _ = fake_ankiconnect
    render_runner = TaskRunner(1, raise_error)
    anki_runner = TaskRunner(2, raise_error)
    draft_store = DraftStore(tmp_path / "state" / "draft.json")
    capture = CapturePage(service, render_runner, anki_runner, draft_store)
    browser = BrowserPage(service, anki_runner)
    global_page = GlobalPage(service, render_runner, anki_runner)
    shortcuts = {action.key: action.default for action in SHORTCUT_ACTIONS}
    main_window = MainWindow(
        gateway, service, capture, browser, global_page, anki_runner, render_runner, shortcuts, []
    )
    qtbot.addWidget(main_window)
    capture.restore(None)
    main_window.show()
    qtbot.waitUntil(lambda: main_window.anki_connected, timeout=WAIT_MS)
    yield main_window
    for _ in range(3):
        anki_runner.wait()
        render_runner.wait()
        QApplication.processEvents()


def type_card(window: MainWindow, deck: str, front: str, back: str) -> None:
    capture = window.capture
    capture.deck_combo.setCurrentText(deck)
    capture.front_editor.setPlainText(front)
    capture.back_editor.setPlainText(back)


def test_save_and_next_adds_note_and_resets_form(
    qtbot: QtBot, window: MainWindow, fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki]
) -> None:
    _, fake = fake_ankiconnect
    capture = window.capture
    type_card(window, "Real Analysis", "*Define* a Cauchy sequence.", "$ forall epsilon > 0 $")
    first_source_id = capture.source_id
    qtbot.keyClick(capture.front_editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    qtbot.waitUntil(lambda: len(fake.notes) == 1, timeout=WAIT_MS)
    qtbot.waitUntil(lambda: not capture.save_in_flight, timeout=WAIT_MS)
    stored = next(iter(fake.notes.values()))
    assert stored.fields[note_type.FRONT_SOURCE] == "*Define* a Cauchy sequence."
    assert stored.deck_name == "Real Analysis"
    assert capture.note_id is None
    assert capture.source_id != first_source_id
    assert capture.deck_name() == "Real Analysis"
    assert (capture.front_editor.toPlainText(), capture.back_editor.toPlainText()) == capture.baseline


def test_compile_error_is_listed_and_blocks_save(
    qtbot: QtBot, window: MainWindow, fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki]
) -> None:
    _, fake = fake_ankiconnect
    capture = window.capture
    type_card(window, "Real Analysis", "fine\n$ nosuchthing(x) $", "back")
    qtbot.waitUntil(lambda: capture.diagnostics_list.count() > 0, timeout=WAIT_MS)
    assert "Front card:2:" in capture.diagnostics_list.item(0).text()
    capture.save_and_next()
    qtbot.waitUntil(lambda: not capture.save_in_flight, timeout=WAIT_MS)
    assert not fake.notes
    assert capture.front_editor.toPlainText().startswith("fine")


def test_save_and_stay_then_edit_updates_same_note(
    qtbot: QtBot, window: MainWindow, fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki]
) -> None:
    _, fake = fake_ankiconnect
    capture = window.capture
    type_card(window, "Real Analysis", "Heine Borel", "closed and bounded")
    capture.save_and_stay()
    qtbot.waitUntil(lambda: capture.note_id is not None, timeout=WAIT_MS)
    capture.back_editor.setPlainText("closed and bounded iff compact")
    capture.save_and_stay()
    qtbot.waitUntil(lambda: not capture.save_in_flight, timeout=WAIT_MS)
    qtbot.waitUntil(
        lambda: (
            next(iter(fake.notes.values())).fields[note_type.BACK_SOURCE] == "closed and bounded iff compact"
        ),
        timeout=WAIT_MS,
    )
    assert len(fake.notes) == 1


def test_browse_search_and_open_for_editing(
    qtbot: QtBot,
    window: MainWindow,
    service: CardService,
    fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki],
) -> None:
    _, fake = fake_ankiconnect
    capture = window.capture
    type_card(
        window, "Real Analysis", "Bolzano Weierstrass", "bounded sequences have convergent subsequences"
    )
    capture.save_and_next()
    qtbot.waitUntil(lambda: len(fake.notes) == 1, timeout=WAIT_MS)
    qtbot.waitUntil(lambda: not capture.save_in_flight, timeout=WAIT_MS)

    window.focus_search()
    browser = window.browser
    qtbot.keyClicks(browser.search_edit, "Bolzano")
    qtbot.waitUntil(lambda: browser.results.count() == 1, timeout=WAIT_MS)
    assert not browser.results.item(0).icon().isNull()

    browser.results.itemActivated.emit(browser.results.item(0))
    qtbot.waitUntil(lambda: capture.note_id is not None, timeout=WAIT_MS)
    assert capture.front_editor.toPlainText() == "Bolzano Weierstrass"
    assert window.tabs.currentIndex() == 0


def test_drift_warning_can_cancel_open(
    qtbot: QtBot,
    window: MainWindow,
    fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, fake = fake_ankiconnect
    capture = window.capture
    type_card(window, "Real Analysis", "drifting card", "back")
    capture.save_and_next()
    qtbot.waitUntil(lambda: len(fake.notes) == 1, timeout=WAIT_MS)
    qtbot.waitUntil(lambda: not capture.save_in_flight, timeout=WAIT_MS)
    note = next(iter(fake.notes.values()))
    note.fields[note_type.BACK] = "edited in Anki"
    warnings: list[str] = []

    def cancel(*args: object) -> QMessageBox.StandardButton:
        warnings.append(str(args[2]))
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "warning", cancel)
    window.open_note(note.note_id)
    qtbot.waitUntil(lambda: bool(warnings), timeout=WAIT_MS)
    assert warnings == ["This card was changed outside Typki. Saving will overwrite those changes."]
    assert capture.note_id is None


def test_draft_restores_after_restart(
    qtbot: QtBot, window: MainWindow, service: CardService, tmp_path: Path
) -> None:
    capture = window.capture
    type_card(window, "Real Analysis", "unsaved thought", "half written")
    capture.save_draft()
    restored_page = CapturePage(
        service,
        TaskRunner(1, raise_error),
        TaskRunner(1, raise_error),
        DraftStore(tmp_path / "state" / "draft.json"),
    )
    qtbot.addWidget(restored_page)
    restored_page.restore(restored_page.draft_store.load())
    assert restored_page.front_editor.toPlainText() == "unsaved thought"
    assert restored_page.source_id == capture.source_id
    restored_page.render_runner.wait()


def save_cards(qtbot: QtBot, window: MainWindow, deck: str, fronts: list[str]) -> None:
    capture = window.capture
    for front in fronts:
        type_card(window, deck, front, "back")
        capture.save_and_next()
        qtbot.waitUntil(lambda: not capture.save_in_flight, timeout=WAIT_MS)


def test_global_tab_shows_and_saves_header(qtbot: QtBot, window: MainWindow, service: CardService) -> None:
    type_card(window, "Real Analysis", "#defn[Field][complete]", "back")
    window.tabs.setCurrentIndex(2)
    global_page = window.global_page
    assert "New Computer Modern" in global_page.header_editor.toPlainText()
    assert global_page.sample_front == "#defn[Field][complete]"
    global_page.header_editor.setFocus()
    global_page.header_editor.setPlainText(global_page.header_editor.toPlainText() + "#let shiny = [new]\n")
    qtbot.waitUntil(lambda: "#let shiny" in service.library.read_header(), timeout=WAIT_MS)


def test_global_tab_uses_sample_when_capture_is_empty(window: MainWindow) -> None:
    window.capture.front_editor.setPlainText("")
    window.capture.back_editor.setPlainText("")
    window.tabs.setCurrentIndex(2)
    assert "compact" in window.global_page.sample_front


def test_header_error_is_listed_and_jumps_to_line(qtbot: QtBot, window: MainWindow) -> None:
    window.tabs.setCurrentIndex(2)
    global_page = window.global_page
    global_page.header_editor.setPlainText("#set text(size: 12pt)\n#let broken = (\n")
    qtbot.waitUntil(lambda: global_page.diagnostics_list.count() > 0, timeout=WAIT_MS)
    assert global_page.diagnostics_list.item(0).text().startswith("header.typ:2:")
    global_page.diagnostics_list.itemActivated.emit(global_page.diagnostics_list.item(0))
    assert global_page.header_editor.textCursor().blockNumber() == 1


def test_rerender_dialog_updates_stale_cards(
    qtbot: QtBot,
    window: MainWindow,
    service: CardService,
    fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki],
) -> None:
    _, fake = fake_ankiconnect
    save_cards(qtbot, window, "Real Analysis", [f"#defn[Term {index}][meaning]" for index in range(5)])
    qtbot.waitUntil(lambda: len(fake.notes) == 5, timeout=WAIT_MS)
    replace_defn(service.library, "#let defn(term, body) = [_#term _ #body]")
    window.open_rerender()
    dialog = window.findChild(RerenderDialog)
    assert dialog is not None
    qtbot.waitUntil(lambda: dialog.apply_button.isVisible(), timeout=WAIT_MS)
    assert dialog.apply_button.text() == "Update 5 cards"
    dialog.apply_button.click()
    qtbot.waitUntil(lambda: dialog.message.text().startswith("Updated 5 cards"), timeout=WAIT_MS)
    assert window.rerenderer.staleness().stale_count == 0


def test_rerender_dialog_blocks_broken_header(
    qtbot: QtBot,
    window: MainWindow,
    service: CardService,
    fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki],
) -> None:
    _, fake = fake_ankiconnect
    save_cards(qtbot, window, "Real Analysis", [f"#defn[Broken {index}][x]" for index in range(3)])
    qtbot.waitUntil(lambda: len(fake.notes) == 3, timeout=WAIT_MS)
    before = {note_id: dict(note.fields) for note_id, note in fake.notes.items()}
    replace_defn(service.library, "#let defn(term, body) = [#nope]")
    window.open_rerender()
    dialog = window.findChild(RerenderDialog)
    assert dialog is not None
    qtbot.waitUntil(lambda: dialog.failures.count() == 1, timeout=WAIT_MS)
    assert dialog.failures.item(0).text().endswith("3 cards")
    assert not dialog.apply_button.isVisible()
    assert {note_id: note.fields for note_id, note in fake.notes.items()} == before
    dialog.failures.itemActivated.emit(dialog.failures.item(0))
    assert window.tabs.currentIndex() == 2
    defn_line = next(
        index for index, line in enumerate(service.library.read_header().splitlines()) if "#nope" in line
    )
    assert window.global_page.header_editor.textCursor().blockNumber() == defn_line


def test_external_header_edit_reloads_global_tab(
    qtbot: QtBot, window: MainWindow, service: CardService
) -> None:
    window.tabs.setCurrentIndex(2)
    window.tabs.setFocus()
    service.library.write_header(service.library.read_header() + "#let external = 1\n")
    qtbot.waitUntil(
        lambda: "#let external" in window.global_page.header_editor.toPlainText(), timeout=WAIT_MS
    )


def test_browse_lists_newest_first_and_filters_as_you_type(
    qtbot: QtBot, window: MainWindow, fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki]
) -> None:
    _, fake = fake_ankiconnect
    save_cards(qtbot, window, "Real Analysis", ["alpha card", "beta card", "gamma card"])
    qtbot.waitUntil(lambda: len(fake.notes) == 3, timeout=WAIT_MS)
    window.tabs.setCurrentIndex(1)
    browser = window.browser
    qtbot.waitUntil(lambda: browser.results.count() == 3, timeout=WAIT_MS)
    newest = max(fake.notes)
    assert browser.results.item(0).data(Qt.ItemDataRole.UserRole) == newest
    qtbot.keyClicks(browser.search_edit, "beta")
    qtbot.waitUntil(lambda: browser.results.count() == 1, timeout=WAIT_MS)


def test_browse_loads_more_on_scroll(
    qtbot: QtBot,
    window: MainWindow,
    service: CardService,
    fake_ankiconnect: tuple[AnkiConnectGateway, FakeAnki],
) -> None:
    for index in range(95):
        service.save(CardDraft("Real Analysis", "", (), f"card number {index}", "back"))
    window.tabs.setCurrentIndex(1)
    browser = window.browser
    qtbot.waitUntil(lambda: browser.results.count() >= 40, timeout=WAIT_MS)
    browser.results.scrollToBottom()
    qtbot.waitUntil(lambda: browser.results.count() >= 80, timeout=WAIT_MS)
    browser.results.scrollToBottom()
    qtbot.waitUntil(lambda: browser.results.count() == 95, timeout=WAIT_MS)


def test_header_templates_fill_front_and_clear_back(
    qtbot: QtBot, window: MainWindow, service: CardService
) -> None:
    capture = window.capture
    assert capture.template_combo.findData("theorem") >= 0
    capture.back_editor.setPlainText("")
    capture.front_editor.setPlainText("")
    capture.template_combo.setCurrentIndex(capture.template_combo.findData("theorem"))
    capture.template_combo.activated.emit(capture.template_combo.currentIndex())
    assert capture.front_editor.toPlainText() == "#theorem[«name»][«statement»]"
    assert capture.front_editor.textCursor().selectedText() == "«name»"
    assert capture.back_editor.toPlainText() == ""
    service.library.write_header(
        service.library.read_header() + "#let lemma(statement) = [*Lemma.* #statement]\n"
    )
    qtbot.waitUntil(lambda: capture.template_combo.findData("lemma") >= 0, timeout=WAIT_MS)

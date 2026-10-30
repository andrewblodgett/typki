import os
from collections.abc import Iterator
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox
from pytestqt.qtbot import QtBot

from typki.anki import note_type
from typki.anki.ankiconnect import AnkiConnectGateway
from typki.anki.fake_anki import FakeAnki
from typki.card_service import CardService
from typki.library.drafts import DraftStore
from typki.ui.background import TaskRunner
from typki.ui.browser import BrowserPage
from typki.ui.capture import CapturePage
from typki.ui.main_window import MainWindow
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
    shortcuts = {action.key: action.default for action in SHORTCUT_ACTIONS}
    main_window = MainWindow(gateway, service, capture, browser, anki_runner, render_runner, shortcuts, [])
    qtbot.addWidget(main_window)
    capture.restore(None)
    main_window.show()
    qtbot.waitUntil(lambda: main_window.anki_connected, timeout=WAIT_MS)
    yield main_window
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
    assert capture.front_editor.toPlainText() == capture.applied_template.front


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
    qtbot.keyClick(browser.search_edit, Qt.Key.Key_Return)
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
        warnings.append(str(args[1]))
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "warning", cancel)
    window.open_note(note.note_id)
    qtbot.waitUntil(lambda: bool(warnings), timeout=WAIT_MS)
    assert warnings == ["Card changed outside Typki"]
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

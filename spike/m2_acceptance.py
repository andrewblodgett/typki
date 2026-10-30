import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from typki.anki.ankiconnect import AnkiConnectGateway
from typki.card_service import CardService
from typki.domain.card import CardDraft
from typki.library.drafts import DraftStore
from typki.library.store import Library
from typki.render.compiler import Renderer
from typki.ui.background import TaskRunner
from typki.ui.browser import BrowserPage
from typki.ui.capture import CapturePage
from typki.ui.main_window import MainWindow
from typki.ui.rerender_dialog import RerenderDialog
from typki.ui.shortcuts import SHORTCUT_ACTIONS
from typki.ui.style_page import StylePage

DECK = "Typki M2 Test"
WORK_DIR = Path(sys.argv[1])
OUT_DIR = Path(__file__).parent / "out"
LIBRARY_ROOT = Path(__file__).parent / "library"
DECK_DIR = LIBRARY_ROOT / "decks" / "m2"
ORIGINAL_MACROS = "#let thm(name, body) = [*Theorem* (#name). #emph(body)]\n"
CHANGED_MACROS = "#let thm(name, body) = block(stroke: (left: 2pt), inset: (left: 6pt))[*#name.* #body]\n"
BROKEN_MACROS = "#let thm(name, body) = [#missing-function(name)]\n"


def wait_until(condition, timeout_s=60.0):
    deadline = time.monotonic() + timeout_s
    while not condition():
        if time.monotonic() > deadline:
            raise TimeoutError("condition not met")
        loop = QEventLoop()
        QTimer.singleShot(20, loop.quit)
        loop.exec()


def pause(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def main():
    app = QApplication(sys.argv[:1])
    DECK_DIR.mkdir(parents=True, exist_ok=True)
    (DECK_DIR / "deck.toml").write_text(f"anki_deck = '{DECK}'\n")
    (DECK_DIR / "macros.typ").write_text(ORIGINAL_MACROS)
    gateway = AnkiConnectGateway()
    library = Library(LIBRARY_ROOT)
    renderer = Renderer(library.root, [library.fonts_dir])
    service = CardService(gateway, library, renderer)
    existing = gateway.find_notes(f'"deck:{DECK}"')
    if existing:
        gateway.delete_notes(existing)
    start = time.perf_counter()
    note_ids = [
        service.save(
            CardDraft(DECK, "blank", ("m2",), f"#thm[Result {index}][$x^{index} >= 0$ for even powers]", f"Proof {index}.")
        ).note_id
        for index in range(50)
    ]
    print(f"created 50 cards in {time.perf_counter() - start:.1f}s")
    first_cards = [record.card_ids[0] for record in gateway.notes_info(note_ids[:3])]
    gateway.invoke("answerCards", answers=[{"cardId": card_id, "ease": 3} for card_id in first_cards])
    reviews_before = gateway.invoke("getReviewsOfCards", cards=first_cards)

    render_runner = TaskRunner(1, lambda error: print("render error", error))
    anki_runner = TaskRunner(2, lambda error: print("anki error", error))
    capture = CapturePage(service, render_runner, anki_runner, DraftStore(WORK_DIR / "draft.json"))
    browser = BrowserPage(service, anki_runner)
    style = StylePage(service, render_runner, anki_runner)
    shortcuts = {action.key: action.default for action in SHORTCUT_ACTIONS}
    window = MainWindow(gateway, service, capture, browser, style, anki_runner, render_runner, shortcuts, [])
    window.resize(1400, 860)
    capture.restore(None)
    window.show()
    wait_until(lambda: window.anki_connected)
    capture.deck_combo.setCurrentText(DECK)
    window.tabs.setCurrentIndex(2)
    style.editor_tabs.setCurrentIndex(1)
    wait_until(lambda: "50 cards" in style.stale_label.text())
    style.deck_macros_editor.setFocus()
    style.deck_macros_editor.setPlainText(CHANGED_MACROS)
    wait_until(lambda: "50 of 50" in style.stale_label.text())
    pause(800)
    window.grab().save(str(OUT_DIR / "m2-style.png"))
    print("stale label:", style.stale_label.text())

    before_broken = {record.note_id: dict(record.fields) for record in gateway.notes_info(note_ids)}
    (DECK_DIR / "macros.typ").write_text(BROKEN_MACROS)
    window.open_rerender(DECK)
    dialog = window.findChild(RerenderDialog)
    wait_until(lambda: dialog.failures.count() == 1)
    print("broken dry run:", dialog.message.text(), "| apply visible:", dialog.apply_button.isVisible())
    pause(300)
    dialog.grab().save(str(OUT_DIR / "m2-dialog-broken.png"))
    after_broken = {record.note_id: dict(record.fields) for record in gateway.notes_info(note_ids)}
    print("no card overwritten by broken macro:", before_broken == after_broken)
    dialog.close_button.click()
    pause(200)

    (DECK_DIR / "macros.typ").write_text(CHANGED_MACROS)
    pause(500)
    window.open_rerender(DECK)
    dialog = [d for d in window.findChildren(RerenderDialog) if d.isVisible()][-1]
    wait_until(lambda: dialog.apply_button.isVisible())
    print("dry run:", dialog.message.text())
    dialog.grab().save(str(OUT_DIR / "m2-dialog-ready.png"))
    start = time.perf_counter()
    dialog.apply_button.click()
    wait_until(lambda: dialog.message.text().startswith("Updated"))
    print(f"apply: {dialog.message.text()} in {time.perf_counter() - start:.1f}s")
    records = gateway.notes_info(note_ids)
    current_hash = library.resolve_deck(DECK).preamble.hash
    print("all 50 updated:", all(record.fields["PreambleHash"] == current_hash for record in records))
    print("review history kept:", gateway.invoke("getReviewsOfCards", cards=first_cards) == reviews_before)
    print("note count:", len(gateway.find_notes(f'"deck:{DECK}"')))
    dialog.close_button.click()
    window.tabs.setCurrentIndex(1)
    browser.search_edit.setText(f'"deck:{DECK}"')
    browser.run_search()
    wait_until(lambda: browser.results.count() == 50)
    pause(300)
    window.grab().save(str(OUT_DIR / "m2-browse.png"))
    window.close()


if __name__ == "__main__":
    main()

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
from typki.library.drafts import DraftStore
from typki.library.store import Library
from typki.render.compiler import Renderer
from typki.ui.background import TaskRunner
from typki.ui.browser import BrowserPage
from typki.ui.capture import CapturePage
from typki.ui.main_window import MainWindow
from typki.ui.shortcuts import SHORTCUT_ACTIONS
from typki.ui.style_page import StylePage

DECK = "Typki M1 Test"
WORK_DIR = Path(sys.argv[1])
OUT_DIR = Path(__file__).parent / "out"
LIBRARY_ROOT = Path(__file__).parent / "library"


def wait_until(condition, timeout_s=20.0):
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


def build_window(gateway, library):
    renderer = Renderer(library.root, [library.fonts_dir])
    service = CardService(gateway, library, renderer)
    render_runner = TaskRunner(1, lambda error: print("render error", error))
    anki_runner = TaskRunner(2, lambda error: print("anki error", error))
    draft_store = DraftStore(WORK_DIR / "draft.json")
    capture = CapturePage(service, render_runner, anki_runner, draft_store)
    browser = BrowserPage(service, anki_runner)
    style = StylePage(service, render_runner, anki_runner)
    shortcuts = {action.key: action.default for action in SHORTCUT_ACTIONS}
    window = MainWindow(gateway, service, capture, browser, style, anki_runner, render_runner, shortcuts, [])
    window.resize(1400, 860)
    capture.status_message.connect(lambda message: print('status:', message) if 'Not saved' in message else None)
    capture.restore(draft_store.load())
    window.show()
    wait_until(lambda: window.anki_connected)
    return window, service


def main():
    app = QApplication(sys.argv[:1])
    gateway = AnkiConnectGateway()
    library = Library(LIBRARY_ROOT)
    library.ensure_layout()
    gateway.create_deck(DECK)
    existing = gateway.find_notes(f'"deck:{DECK}"')
    if existing:
        gateway.delete_notes(existing)

    window, service = build_window(gateway, library)
    capture = window.capture
    capture.deck_combo.setCurrentText(DECK)
    start = time.perf_counter()
    for index in range(1, 21):
        capture.front_editor.setPlainText(f"#defn[Card {index}][$ sum_(k=1)^{index} k = {index * (index + 1) // 2} $]")
        capture.back_editor.setPlainText(f"Triangular number $T_{{{index}}}$ with $abs(x) <= {index}$.")
        capture.save_and_next()
        wait_until(lambda: not capture.save_in_flight)
    print(f"created 20 cards in {time.perf_counter() - start:.1f}s")

    capture.front_editor.setPlainText("#defn[Uniform continuity][\n  $ forall epsilon > 0 space exists delta > 0 : abs(x - y) < delta ==> abs(f(x) - f(y)) < epsilon $\n]")
    capture.back_editor.setPlainText("Every continuous function on a compact set is $undefined-thing$ continuous.")
    pause(1500)
    window.grab().save(str(OUT_DIR / "m1-capture.png"))
    capture.back_editor.setPlainText("Every continuous function on a compact set is uniformly continuous.")
    capture.preview.dark_toggle.setChecked(True)
    pause(1500)
    window.grab().save(str(OUT_DIR / "m1-capture-dark.png"))
    capture.front_editor.setPlainText("")
    capture.back_editor.setPlainText("")
    capture.save_draft()
    window.close()
    window.deleteLater()
    pause(200)

    note_ids = sorted(gateway.find_notes(f'"deck:{DECK}"'))
    to_edit = note_ids[:3]
    card_ids = [record.card_ids[0] for record in gateway.notes_info(to_edit)]
    gateway.invoke("answerCards", answers=[{"cardId": card_id, "ease": 3} for card_id in card_ids])
    reviews_before = gateway.invoke("getReviewsOfCards", cards=card_ids)

    window, service = build_window(gateway, library)
    capture = window.capture
    browser = window.browser
    window.focus_search()
    browser.search_edit.setText(f'"deck:{DECK}"')
    browser.run_search()
    wait_until(lambda: browser.results.count() == 20)
    pause(300)
    window.grab().save(str(OUT_DIR / "m1-browse.png"))

    for note_id in to_edit:
        window.open_note(note_id)
        wait_until(lambda: capture.note_id == note_id)
        capture.back_editor.setPlainText(capture.back_editor.toPlainText() + " Edited.")
        capture.save_and_next()
        wait_until(lambda: not capture.save_in_flight and capture.note_id is None)

    records = gateway.notes_info(sorted(gateway.find_notes(f'"deck:{DECK}"')))
    reviews_after = gateway.invoke("getReviewsOfCards", cards=card_ids)
    fronts = [record.fields["FrontSrc"] for record in records]
    edited = [record for record in records if record.fields["BackSrc"].endswith(" Edited.")]
    print(f"notes in deck: {len(records)}, unique fronts: {len(set(fronts))}")
    print(f"edited notes: {sorted(r.note_id for r in edited) == to_edit}")
    print(f"review history kept: {reviews_before == reviews_after and all(reviews_after[str(c)] for c in card_ids)}")
    window.close()


if __name__ == "__main__":
    main()

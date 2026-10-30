import json
import sys
import urllib.request
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

from m0_anki import CARD_CSS, MODEL_NAME, call

OUTPUT_DIR = Path(__file__).parent / "out"


def page_html(answer_html, night_mode):
    body_class = "card nightMode" if night_mode else "card"
    return f"<!doctype html><html><head><style>{CARD_CSS} body{{margin:0;padding:16px}}</style></head><body class='{body_class}'>{answer_html}</body></html>"


def main():
    note_ids = call("findNotes", query=f'"note:{MODEL_NAME}" deck:"Typki Spike"')
    card_ids = call("notesInfo", notes=note_ids[-1:])[0]["cards"]
    answer_html = call("cardsInfo", cards=card_ids)[0]["answer"]
    answer_body = answer_html.split("</style>", 1)[-1]

    app = QApplication(sys.argv)
    targets = [("light", False, 800), ("dark", True, 800), ("phone-dark", True, 380)]
    views = []

    def shoot(index):
        if index == len(targets):
            app.quit()
            return
        name, night_mode, width = targets[index]
        view = QWebEngineView()
        views.append(view)
        view.resize(width, 900)

        def on_loaded(_ok):
            QTimer.singleShot(1500, lambda: (view.grab().save(str(OUTPUT_DIR / f"answer-{name}.png")), shoot(index + 1)))

        view.loadFinished.connect(on_loaded)
        view.setHtml(page_html(answer_body, night_mode), QUrl("file:///"))
        view.show()

    shoot(0)
    app.exec()


if __name__ == "__main__":
    main()

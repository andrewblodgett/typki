import json

from PySide6.QtCore import QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QVBoxLayout, QWidget

from typki.anki.note_type import CARD_CSS

PHONE_WIDTH_PX = 360

PREVIEW_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><style>
%(card_css)s
html, body { margin: 0; min-height: 100%%; }
body { padding: 16px; box-sizing: border-box; }
#frame { margin: 0 auto; }
body.phone #frame {
  max-width: %(phone)dpx;
  outline: 1px dashed rgba(128,128,128,.5);
  outline-offset: 8px;
}
.failed { opacity: .35; }
.empty-side { min-height: 1.5em; }
</style>
<script>
function setSide(id, svg, failed) {
  const element = document.getElementById(id);
  if (svg !== null) { element.innerHTML = svg; }
  element.classList.toggle("failed", failed);
}
function setMode(dark, phone) {
  document.body.classList.toggle("nightMode", dark);
  document.body.classList.toggle("night_mode", dark);
  document.body.classList.toggle("phone", phone);
}
</script></head>
<body class="card"><div id="frame">
<div id="front" class="empty-side"></div><hr id="answer"><div id="back" class="empty-side"></div>
</div></body></html>
"""


class CardPreview(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.view = QWebEngineView(self)
        self.dark_toggle = QCheckBox("Dark")
        self.phone_toggle = QCheckBox("Phone width")
        self.loaded = False
        self.pending_scripts: list[str] = []

        controls = QHBoxLayout()
        controls.addWidget(self.dark_toggle)
        controls.addWidget(self.phone_toggle)
        controls.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(controls)
        layout.addWidget(self.view, 1)

        self.dark_toggle.toggled.connect(self.apply_mode)
        self.phone_toggle.toggled.connect(self.apply_mode)
        self.view.loadFinished.connect(self.on_loaded)
        page = PREVIEW_PAGE % {"card_css": CARD_CSS, "phone": PHONE_WIDTH_PX}
        self.view.setHtml(page, QUrl("about:blank"))

    def on_loaded(self, _ok: bool) -> None:
        self.loaded = True
        scripts, self.pending_scripts = self.pending_scripts, []
        for script in scripts:
            self.view.page().runJavaScript(script)
        self.apply_mode()

    def run_script(self, script: str) -> None:
        if self.loaded:
            self.view.page().runJavaScript(script)
        else:
            self.pending_scripts.append(script)

    def set_side(self, side: str, svg: str | None, failed: bool) -> None:
        self.run_script(f"setSide({json.dumps(side)}, {json.dumps(svg)}, {json.dumps(failed)})")

    def clear(self) -> None:
        self.set_side("front", "", False)
        self.set_side("back", "", False)

    def apply_mode(self) -> None:
        dark = json.dumps(self.dark_toggle.isChecked())
        phone = json.dumps(self.phone_toggle.isChecked())
        self.run_script(f"setMode({dark}, {phone})")

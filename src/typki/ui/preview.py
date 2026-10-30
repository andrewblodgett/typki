import json

from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QHBoxLayout, QToolButton, QVBoxLayout, QWidget

from typki.anki.note_type import CARD_CSS
from typki.ui.theme import DEFAULT_THEME, Theme

PHONE_WIDTH_PX = 360

PREVIEW_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><style>
%(card_css)s
:root { --page: #000; --card: #000; --text: #fff; --border: #444; }
html, body { margin: 0; min-height: 100%%; background: var(--page); }
body.card { padding: 0 4px 16px 4px; box-sizing: border-box; color: var(--text); background: var(--page); }
#frame {
  margin: 0 auto; padding: 28px 24px; border-radius: 14px; background: var(--card);
  transition: max-width .15s ease;
}
body.phone #frame { max-width: %(phone)dpx; }
hr#answer { border: none; border-top: 1px solid var(--border); margin: 22px 0; }
.failed { opacity: .35; }
.empty-side { min-height: 1.5em; }
</style>
<script>
function setSide(id, svg, failed) {
  const element = document.getElementById(id);
  if (svg !== null) { element.innerHTML = svg; }
  element.classList.toggle("failed", failed);
}
function setPhone(phone) {
  document.body.classList.toggle("phone", phone);
}
function setTheme(colors) {
  for (const [name, value] of Object.entries(colors)) {
    document.documentElement.style.setProperty("--" + name, value);
  }
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
        self.phone_toggle = QToolButton()
        self.phone_toggle.setText("Phone width")
        self.phone_toggle.setCheckable(True)
        self.loaded = False
        self.pending_scripts: list[str] = []
        self.theme = DEFAULT_THEME

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 4)
        controls.addStretch(1)
        controls.addWidget(self.phone_toggle)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(controls)
        layout.addWidget(self.view, 1)

        self.phone_toggle.toggled.connect(self.apply_phone)
        self.view.loadFinished.connect(self.on_loaded)
        self.view.page().setBackgroundColor(QColor(self.theme.chrome))
        page = PREVIEW_PAGE % {"card_css": CARD_CSS, "phone": PHONE_WIDTH_PX}
        self.view.setHtml(page, QUrl("about:blank"))

    def on_loaded(self, _ok: bool) -> None:
        self.loaded = True
        scripts, self.pending_scripts = self.pending_scripts, []
        self.apply_theme_colors()
        for script in scripts:
            self.view.page().runJavaScript(script)
        self.apply_phone()

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

    def apply_phone(self) -> None:
        self.run_script(f"setPhone({json.dumps(self.phone_toggle.isChecked())})")

    def set_theme(self, theme: Theme) -> None:
        self.theme = theme
        self.view.page().setBackgroundColor(QColor(theme.chrome))
        if self.loaded:
            self.apply_theme_colors()

    def apply_theme_colors(self) -> None:
        colors = {
            "page": self.theme.chrome,
            "card": self.theme.panel,
            "text": self.theme.text,
            "border": self.theme.border,
        }
        self.view.page().runJavaScript(f"setTheme({json.dumps(colors)})")

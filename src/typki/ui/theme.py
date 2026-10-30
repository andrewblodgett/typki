import tempfile
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

UI_FONT_FAMILIES = ("Inter", "Inter Variable", "SF Pro Text", "Segoe UI Variable", "Cantarell", "Noto Sans")
CODE_FONT_FAMILIES = (
    "JetBrains Mono",
    "Cascadia Code",
    "Fira Code",
    "Iosevka",
    "SF Mono",
    "Source Code Pro",
    "Fira Mono",
    "Ubuntu Mono",
)
CHEVRON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 12 12">'
    '<path d="M2.5 4.5 6 8l3.5-3.5" fill="none" stroke="{color}" stroke-width="1.6" '
    'stroke-linecap="round" stroke-linejoin="round"/></svg>'
)
UI_FONT_POINT_SIZE = 10.5
CODE_FONT_POINT_SIZE = 11.5


@dataclass(frozen=True)
class Theme:
    name: str
    dark: bool
    chrome: str
    panel: str
    raised: str
    border: str
    selection: str
    text: str
    muted: str
    accent: str
    error: str
    warning: str
    keyword: str
    function: str
    string: str
    number: str
    math: str
    comment: str
    heading: str


THEMES: tuple[Theme, ...] = (
    Theme(
        name="Everforest",
        dark=True,
        chrome="#2d353b",
        panel="#343f44",
        raised="#3d484d",
        border="#475258",
        selection="#475258",
        text="#d3c6aa",
        muted="#859289",
        accent="#a7c080",
        error="#e67e80",
        warning="#dbbc7f",
        keyword="#e67e80",
        function="#a7c080",
        string="#83c092",
        number="#d699b6",
        math="#7fbbb3",
        comment="#859289",
        heading="#e69875",
    ),
    Theme(
        name="Rosé Pine",
        dark=True,
        chrome="#191724",
        panel="#1f1d2e",
        raised="#26233a",
        border="#403d52",
        selection="#403d52",
        text="#e0def4",
        muted="#908caa",
        accent="#c4a7e7",
        error="#eb6f92",
        warning="#f6c177",
        keyword="#c4a7e7",
        function="#ebbcba",
        string="#f6c177",
        number="#eb6f92",
        math="#9ccfd8",
        comment="#6e6a86",
        heading="#ebbcba",
    ),
    Theme(
        name="Tokyo Night",
        dark=True,
        chrome="#16161e",
        panel="#1a1b26",
        raised="#292e42",
        border="#3b4261",
        selection="#33467c",
        text="#c0caf5",
        muted="#737aa2",
        accent="#7aa2f7",
        error="#f7768e",
        warning="#e0af68",
        keyword="#bb9af7",
        function="#7aa2f7",
        string="#9ece6a",
        number="#ff9e64",
        math="#7dcfff",
        comment="#565f89",
        heading="#ff9e64",
    ),
    Theme(
        name="Nord",
        dark=True,
        chrome="#2e3440",
        panel="#3b4252",
        raised="#434c5e",
        border="#4c566a",
        selection="#4c566a",
        text="#eceff4",
        muted="#9aa3b5",
        accent="#88c0d0",
        error="#bf616a",
        warning="#ebcb8b",
        keyword="#81a1c1",
        function="#88c0d0",
        string="#a3be8c",
        number="#b48ead",
        math="#8fbcbb",
        comment="#7b88a1",
        heading="#d08770",
    ),
    Theme(
        name="Gruvbox",
        dark=True,
        chrome="#282828",
        panel="#32302f",
        raised="#3c3836",
        border="#504945",
        selection="#504945",
        text="#ebdbb2",
        muted="#a89984",
        accent="#fabd2f",
        error="#fb4934",
        warning="#fabd2f",
        keyword="#fb4934",
        function="#fabd2f",
        string="#b8bb26",
        number="#d3869b",
        math="#83a598",
        comment="#928374",
        heading="#fe8019",
    ),
    Theme(
        name="Kanagawa",
        dark=True,
        chrome="#16161d",
        panel="#1f1f28",
        raised="#2a2a37",
        border="#363646",
        selection="#2d4f67",
        text="#dcd7ba",
        muted="#727169",
        accent="#7e9cd8",
        error="#ff5d62",
        warning="#e6c384",
        keyword="#957fb8",
        function="#7e9cd8",
        string="#98bb6c",
        number="#d27e99",
        math="#7fb4ca",
        comment="#727169",
        heading="#ffa066",
    ),
    Theme(
        name="Dracula",
        dark=True,
        chrome="#21222c",
        panel="#282a36",
        raised="#343746",
        border="#44475a",
        selection="#44475a",
        text="#f8f8f2",
        muted="#8b93c2",
        accent="#bd93f9",
        error="#ff5555",
        warning="#f1fa8c",
        keyword="#ff79c6",
        function="#50fa7b",
        string="#f1fa8c",
        number="#bd93f9",
        math="#8be9fd",
        comment="#6272a4",
        heading="#ffb86c",
    ),
    Theme(
        name="One Dark",
        dark=True,
        chrome="#21252b",
        panel="#282c34",
        raised="#2c313a",
        border="#3e4451",
        selection="#3e4451",
        text="#abb2bf",
        muted="#7f848e",
        accent="#61afef",
        error="#e06c75",
        warning="#e5c07b",
        keyword="#c678dd",
        function="#61afef",
        string="#98c379",
        number="#d19a66",
        math="#56b6c2",
        comment="#5c6370",
        heading="#e06c75",
    ),
    Theme(
        name="Solarized Dark",
        dark=True,
        chrome="#002b36",
        panel="#073642",
        raised="#0d4250",
        border="#2c5561",
        selection="#274f5a",
        text="#93a1a1",
        muted="#657b83",
        accent="#268bd2",
        error="#dc322f",
        warning="#b58900",
        keyword="#859900",
        function="#268bd2",
        string="#2aa198",
        number="#d33682",
        math="#6c71c4",
        comment="#586e75",
        heading="#cb4b16",
    ),
    Theme(
        name="Everforest Light",
        dark=False,
        chrome="#f4f0d9",
        panel="#fdf6e3",
        raised="#efebd4",
        border="#e0dcc7",
        selection="#e6e2cc",
        text="#5c6a72",
        muted="#829181",
        accent="#8da101",
        error="#f85552",
        warning="#dfa000",
        keyword="#f85552",
        function="#8da101",
        string="#35a77c",
        number="#df69ba",
        math="#3a94c5",
        comment="#939f91",
        heading="#f57d26",
    ),
    Theme(
        name="Rosé Pine Dawn",
        dark=False,
        chrome="#faf4ed",
        panel="#fffaf3",
        raised="#f2e9e1",
        border="#dfdad9",
        selection="#dfdad9",
        text="#575279",
        muted="#797593",
        accent="#907aa9",
        error="#b4637a",
        warning="#ea9d34",
        keyword="#907aa9",
        function="#d7827e",
        string="#ea9d34",
        number="#b4637a",
        math="#56949f",
        comment="#9893a5",
        heading="#286983",
    ),
    Theme(
        name="Catppuccin Latte",
        dark=False,
        chrome="#e6e9ef",
        panel="#eff1f5",
        raised="#ccd0da",
        border="#bcc0cc",
        selection="#ccd0da",
        text="#4c4f69",
        muted="#7c7f93",
        accent="#8839ef",
        error="#d20f39",
        warning="#df8e1d",
        keyword="#8839ef",
        function="#1e66f5",
        string="#40a02b",
        number="#fe640b",
        math="#179299",
        comment="#9ca0b0",
        heading="#d20f39",
    ),
    Theme(
        name="Gruvbox Light",
        dark=False,
        chrome="#f2e5bc",
        panel="#fbf1c7",
        raised="#ebdbb2",
        border="#d5c4a1",
        selection="#d5c4a1",
        text="#3c3836",
        muted="#7c6f64",
        accent="#b57614",
        error="#9d0006",
        warning="#b57614",
        keyword="#9d0006",
        function="#b57614",
        string="#79740e",
        number="#8f3f71",
        math="#076678",
        comment="#928374",
        heading="#af3a03",
    ),
    Theme(
        name="Solarized Light",
        dark=False,
        chrome="#eee8d5",
        panel="#fdf6e3",
        raised="#e9e2cb",
        border="#d3cbb7",
        selection="#e3dcc6",
        text="#586e75",
        muted="#93a1a1",
        accent="#268bd2",
        error="#dc322f",
        warning="#b58900",
        keyword="#859900",
        function="#268bd2",
        string="#2aa198",
        number="#d33682",
        math="#6c71c4",
        comment="#93a1a1",
        heading="#cb4b16",
    ),
    Theme(
        name="Tokyo Night Day",
        dark=False,
        chrome="#d0d5e3",
        panel="#e1e2e7",
        raised="#c4c8da",
        border="#a8aecb",
        selection="#b6bfe2",
        text="#3760bf",
        muted="#6172b0",
        accent="#2e7de9",
        error="#f52a65",
        warning="#8c6c3e",
        keyword="#9854f1",
        function="#2e7de9",
        string="#587539",
        number="#b15c00",
        math="#007197",
        comment="#848cb5",
        heading="#f52a65",
    ),
    Theme(
        name="GitHub Light",
        dark=False,
        chrome="#f6f8fa",
        panel="#ffffff",
        raised="#eaeef2",
        border="#d0d7de",
        selection="#ddf4ff",
        text="#1f2328",
        muted="#656d76",
        accent="#0969da",
        error="#cf222e",
        warning="#9a6700",
        keyword="#cf222e",
        function="#8250df",
        string="#0a3069",
        number="#0550ae",
        math="#116329",
        comment="#6e7781",
        heading="#bc4c00",
    ),
)
DEFAULT_THEME = THEMES[0]


def find_theme(name: object) -> Theme:
    return next((theme for theme in THEMES if theme.name == name), DEFAULT_THEME)


def first_installed_family(candidates: tuple[str, ...]) -> str | None:
    installed = set(QFontDatabase.families())
    return next((family for family in candidates if family in installed), None)


def preferred_font(fallback: QFontDatabase.SystemFont, families: tuple[str, ...], point_size: float) -> QFont:
    font = QFontDatabase.systemFont(fallback)
    family = first_installed_family(families)
    if family is not None:
        font.setFamily(family)
    font.setPointSizeF(point_size)
    return font


def ui_font() -> QFont:
    return preferred_font(QFontDatabase.SystemFont.GeneralFont, UI_FONT_FAMILIES, UI_FONT_POINT_SIZE)


def code_font() -> QFont:
    return preferred_font(QFontDatabase.SystemFont.FixedFont, CODE_FONT_FAMILIES, CODE_FONT_POINT_SIZE)


def icon_directory() -> Path:
    cache = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)
    return Path(cache or tempfile.gettempdir()) / "typki-icons"


def chevron_path(color: str) -> str:
    path = icon_directory() / f"chevron-{color.lstrip('#')}.svg"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(CHEVRON_SVG.format(color=color))
    return path.as_posix()


def palette_for(theme: Theme) -> QPalette:
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: theme.chrome,
        QPalette.ColorRole.WindowText: theme.text,
        QPalette.ColorRole.Base: theme.panel,
        QPalette.ColorRole.AlternateBase: theme.raised,
        QPalette.ColorRole.Text: theme.text,
        QPalette.ColorRole.Button: theme.raised,
        QPalette.ColorRole.ButtonText: theme.text,
        QPalette.ColorRole.BrightText: theme.error,
        QPalette.ColorRole.Highlight: theme.selection,
        QPalette.ColorRole.HighlightedText: theme.text,
        QPalette.ColorRole.PlaceholderText: theme.muted,
        QPalette.ColorRole.Link: theme.accent,
        QPalette.ColorRole.LinkVisited: theme.accent,
        QPalette.ColorRole.ToolTipBase: theme.raised,
        QPalette.ColorRole.ToolTipText: theme.text,
        QPalette.ColorRole.Light: theme.raised,
        QPalette.ColorRole.Midlight: theme.raised,
        QPalette.ColorRole.Mid: theme.border,
        QPalette.ColorRole.Dark: theme.chrome,
        QPalette.ColorRole.Shadow: theme.chrome,
    }
    for role, color in roles.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(theme.muted))
    return palette


def stylesheet_for(theme: Theme) -> str:
    chevron = chevron_path(theme.muted)
    return f"""
QMainWindow, QStackedWidget, QTabWidget::pane {{ background: {theme.chrome}; border: none; }}
QLabel {{ background: transparent; }}
QStatusBar {{ background: {theme.chrome}; border: none; }}
QStatusBar QLabel {{ color: {theme.muted}; padding: 2px 12px 6px 12px; }}
QTabBar {{ background: transparent; qproperty-drawBase: 0; }}
QTabBar::tab {{
  background: transparent; color: {theme.muted}; border: none;
  border-bottom: 2px solid transparent; padding: 10px 4px 8px 4px; margin: 0 10px;
}}
QTabBar::tab:first {{ margin-left: 16px; }}
QTabBar::tab:selected {{ color: {theme.text}; border-bottom: 2px solid {theme.accent}; }}
QTabBar::tab:hover:!selected {{ color: {theme.text}; }}
QPlainTextEdit, QLineEdit, QComboBox, QListWidget {{
  background: {theme.panel}; color: {theme.text}; border: 1px solid {theme.panel}; border-radius: 10px;
  selection-background-color: {theme.selection}; selection-color: {theme.text};
}}
QPlainTextEdit {{ padding: 10px 12px; }}
QLineEdit {{ padding: 7px 12px; }}
QComboBox {{ padding: 7px 12px; }}
QComboBox:editable {{ background: {theme.panel}; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox::down-arrow {{ image: url("{chevron}"); width: 12px; height: 12px; }}
QPlainTextEdit:focus, QLineEdit:focus, QComboBox:focus, QComboBox:on {{ border: 1px solid {theme.accent}; }}
QComboBox QAbstractItemView {{
  background: {theme.raised}; color: {theme.text}; border: 1px solid {theme.border};
  padding: 4px; outline: 0; selection-background-color: {theme.selection};
}}
QListWidget {{ padding: 6px; outline: 0; }}
QListView#completions {{
  background: {theme.raised}; color: {theme.text}; border: 1px solid {theme.border}; border-radius: 8px;
  padding: 4px; outline: 0;
}}
QListView#completions::item {{ padding: 4px 8px; border-radius: 6px; }}
QListView#completions::item:selected {{ background: {theme.selection}; color: {theme.text}; }}
QListWidget::item {{ padding: 10px; border-radius: 8px; }}
QListWidget::item:selected {{ background: {theme.raised}; }}
QListWidget::item:hover:!selected {{ background: {theme.raised}; }}
QListWidget#cards {{ background: transparent; border: none; padding: 0; }}
QListWidget#cards::item {{
  color: {theme.muted};
  background: {theme.panel}; border: 1px solid {theme.panel}; border-radius: 12px; margin: 5px; padding: 6px;
}}
QListWidget#cards::item:hover {{ background: {theme.raised}; border-color: {theme.raised}; }}
QListWidget#cards::item:selected {{
  background: {theme.raised}; border-color: {theme.accent}; color: {theme.text};
}}
QLabel#caption {{ color: {theme.muted}; font-weight: 600; padding-left: 2px; }}
QLabel#message {{ color: {theme.muted}; padding: 0 2px; }}
QLabel#save-status {{ color: {theme.muted}; padding: 0 8px; }}
QLabel#message[level="error"], QLabel#save-status[level="error"] {{ color: {theme.error}; }}
QLabel#message[level="warning"] {{ color: {theme.warning}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px 4px; }}
QScrollBar::handle {{ background: {theme.border}; border-radius: 3px; }}
QScrollBar::handle:vertical {{ min-height: 32px; }}
QScrollBar::handle:horizontal {{ min-width: 32px; }}
QScrollBar::handle:hover {{ background: {theme.muted}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QSplitter::handle {{ background: transparent; }}
QPushButton {{
  background: {theme.raised}; color: {theme.text}; border: none; border-radius: 8px; padding: 7px 16px;
}}
QPushButton:hover {{ background: {theme.border}; }}
QPushButton#primary {{
  background: {theme.accent}; color: {theme.chrome}; font-weight: 600; padding: 8px 20px;
}}
QPushButton#primary:hover {{ background: {theme.text}; }}
QPushButton:flat {{ background: transparent; color: {theme.muted}; padding: 7px 0; }}
QPushButton:flat:hover {{ color: {theme.text}; }}
QToolButton {{
  background: transparent; color: {theme.muted}; border: none; border-radius: 8px; padding: 5px 10px;
}}
QToolButton:hover {{ background: {theme.raised}; color: {theme.text}; }}
QToolButton:checked {{ color: {theme.accent}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}
QMenu {{ background: {theme.raised}; color: {theme.text}; border: 1px solid {theme.border}; padding: 6px; }}
QMenu::item {{ padding: 6px 28px 6px 14px; border-radius: 6px; }}
QMenu::item:selected {{ background: {theme.selection}; }}
QMenu::item:disabled {{ color: {theme.muted}; }}
QMenu::separator {{ height: 1px; background: {theme.border}; margin: 5px 8px; }}
QToolTip {{
  background: {theme.raised}; color: {theme.text}; border: 1px solid {theme.border}; padding: 5px 8px;
}}
"""


def apply_to_application(app: QApplication, theme: Theme) -> None:
    if app.style().name().lower() != "fusion":
        app.setStyle("Fusion")
    app.setFont(ui_font())
    app.setPalette(palette_for(theme))
    app.setStyleSheet(stylesheet_for(theme))

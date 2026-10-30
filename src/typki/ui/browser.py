from dataclasses import dataclass

from PySide6.QtCore import QByteArray, QEvent, QObject, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QImage, QKeyEvent, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from typki.anki.gateway import AnkiUnavailableError
from typki.card_service import CardService, SearchResult
from typki.render.plain_text import plain_text_from_source
from typki.render.svg_postprocess import svg_for_display
from typki.ui.background import TaskRunner

THUMBNAIL_WIDTH = 280
THUMBNAIL_MAX_HEIGHT = 120
NOTE_ID_ROLE = Qt.ItemDataRole.UserRole
STALE_MARKER = "● stale"


@dataclass(frozen=True)
class BrowseResult:
    search: SearchResult
    thumbnails: tuple[QImage, ...]


def render_thumbnail(svg_text: str, color: str) -> QImage:
    renderer = QSvgRenderer(QByteArray(svg_for_display(svg_text, color).encode()))
    image = QImage(THUMBNAIL_WIDTH, THUMBNAIL_MAX_HEIGHT, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    if not renderer.isValid():
        return image
    size = renderer.defaultSize()
    if size.width() <= 0:
        return image
    height = THUMBNAIL_WIDTH * size.height() / size.width()
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, THUMBNAIL_WIDTH, height))
    painter.end()
    return image


def search_with_thumbnails(service: CardService, query: str, color: str) -> BrowseResult:
    search = service.search(query)
    thumbnails = tuple(render_thumbnail(summary.card.front_svg, color) for summary in search.cards)
    return BrowseResult(search=search, thumbnails=thumbnails)


class BrowserPage(QWidget):
    open_requested = Signal(object)
    status_message = Signal(str)

    def __init__(self, service: CardService, anki_runner: TaskRunner, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.anki_runner = anki_runner
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText('Anki search, e.g. deck:"Real Analysis" tag:topology compact')
        self.search_edit.setClearButtonEnabled(True)
        self.search_button = QPushButton("Search")
        self.results = QListWidget()
        self.results.setIconSize(QSize(THUMBNAIL_WIDTH, THUMBNAIL_MAX_HEIGHT))
        self.results.setSpacing(4)
        self.results.setUniformItemSizes(True)
        self.summary_label = QLabel()

        search_row = QHBoxLayout()
        search_row.addWidget(self.search_edit, 1)
        search_row.addWidget(self.search_button)
        layout = QVBoxLayout(self)
        layout.addLayout(search_row)
        layout.addWidget(self.results, 1)
        layout.addWidget(self.summary_label)

        self.search_edit.returnPressed.connect(self.run_search)
        self.search_button.clicked.connect(self.run_search)
        self.results.itemActivated.connect(self.on_item_activated)
        self.search_edit.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.search_edit and event.type() == QEvent.Type.KeyPress:
            assert isinstance(event, QKeyEvent)
            if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up) and self.results.count():
                self.results.setFocus()
                if self.results.currentRow() < 0:
                    self.results.setCurrentRow(0)
                return True
        return super().eventFilter(watched, event)

    def focus_search(self) -> None:
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def run_search(self) -> None:
        query = self.search_edit.text().strip()
        color = self.palette().text().color().name()
        self.summary_label.setText("Searching…")
        self.anki_runner.run(
            lambda: search_with_thumbnails(self.service, query, color),
            self.show_results,
            self.on_search_failed,
        )

    def show_results(self, result: BrowseResult) -> None:
        self.results.clear()
        for summary, thumbnail in zip(result.search.cards, result.thumbnails, strict=True):
            card = summary.card
            title = plain_text_from_source(card.front_source) or "(empty front)"
            details = card.deck_name
            if card.tags:
                details += " · " + " ".join(card.tags)
            if summary.stale:
                details += f"  {STALE_MARKER}"
            item = QListWidgetItem(f"{title}\n{details}")
            item.setIcon(QPixmap.fromImage(thumbnail))
            item.setData(NOTE_ID_ROLE, card.note_id)
            item.setToolTip(card.front_source)
            self.results.addItem(item)
        shown = len(result.search.cards)
        stale = sum(1 for summary in result.search.cards if summary.stale)
        prefix = (
            f"Showing {shown} of {result.search.total}" if shown < result.search.total else f"{shown} cards"
        )
        self.summary_label.setText(f"{prefix} · {stale} stale")
        if shown:
            self.results.setCurrentRow(0)

    def on_search_failed(self, error: Exception) -> None:
        if isinstance(error, AnkiUnavailableError):
            self.summary_label.setText("Anki is not reachable.")
        else:
            self.summary_label.setText(f"Search failed: {error}")

    def on_item_activated(self, item: QListWidgetItem) -> None:
        self.open_requested.emit(int(item.data(NOTE_ID_ROLE)))

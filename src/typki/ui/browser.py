from dataclasses import dataclass

from PySide6.QtCore import QByteArray, QEvent, QObject, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QImage, QKeyEvent, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QLineEdit, QListView, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from typki.card_service import CardService, SearchResult
from typki.render.svg_postprocess import svg_for_display
from typki.ui.background import TaskRunner

THUMBNAIL_WIDTH = 320
THUMBNAIL_MAX_HEIGHT = 150
THUMBNAIL_PIXELS_PER_POINT = 1.2
TILE_PADDING = 28
TILE_CAPTION_HEIGHT = 40
SEARCH_DEBOUNCE_MS = 250
PAGE_SIZE = 40
LOAD_MORE_MARGIN = 3
NOTE_ID_ROLE = Qt.ItemDataRole.UserRole
STALE_MARKER = "stale"


@dataclass(frozen=True)
class BrowsePage:
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
    scale = min(
        THUMBNAIL_PIXELS_PER_POINT,
        THUMBNAIL_WIDTH / size.width(),
        THUMBNAIL_MAX_HEIGHT / max(size.height(), 1),
    )
    width, height = size.width() * scale, size.height() * scale
    left, top = (THUMBNAIL_WIDTH - width) / 2, (THUMBNAIL_MAX_HEIGHT - height) / 2
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(left, top, width, height))
    painter.end()
    return image


def load_page(service: CardService, query: str, offset: int, color: str) -> BrowsePage:
    search = service.search(query, offset=offset, limit=PAGE_SIZE)
    thumbnails = tuple(render_thumbnail(summary.card.front_svg, color) for summary in search.cards)
    return BrowsePage(search=search, thumbnails=thumbnails)


DELETE_SHORTCUT = "Ctrl+Delete"


class BrowserPage(QWidget):
    open_requested = Signal(object)
    delete_requested = Signal(object)

    def __init__(self, service: CardService, anki_runner: TaskRunner, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.anki_runner = anki_runner
        self.generation = 0
        self.loading = False
        self.total = 0
        self.search_edit = QLineEdit()
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setPlaceholderText("Search")
        self.results = QListWidget()
        self.results.setObjectName("cards")
        self.results.setViewMode(QListView.ViewMode.IconMode)
        self.results.setMovement(QListView.Movement.Static)
        self.results.setResizeMode(QListView.ResizeMode.Adjust)
        self.results.setWrapping(True)
        self.results.setWordWrap(False)
        self.results.setIconSize(QSize(THUMBNAIL_WIDTH, THUMBNAIL_MAX_HEIGHT))
        self.results.setGridSize(
            QSize(THUMBNAIL_WIDTH + TILE_PADDING, THUMBNAIL_MAX_HEIGHT + TILE_PADDING + TILE_CAPTION_HEIGHT)
        )
        self.results.setUniformItemSizes(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 4)
        layout.setSpacing(8)
        layout.addWidget(self.search_edit)
        layout.addWidget(self.results, 1)

        self.search_timer = QTimer(self, singleShot=True, interval=SEARCH_DEBOUNCE_MS)
        self.search_timer.timeout.connect(self.refresh)
        self.search_edit.textChanged.connect(self.search_timer.start)
        self.search_edit.returnPressed.connect(self.refresh)
        self.results.itemActivated.connect(self.on_item_activated)
        self.results.verticalScrollBar().valueChanged.connect(self.on_scrolled)
        self.search_edit.installEventFilter(self)
        delete_shortcut = QShortcut(QKeySequence(DELETE_SHORTCUT), self.results)
        delete_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        delete_shortcut.activated.connect(self.request_delete)

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

    def refresh(self) -> None:
        self.search_timer.stop()
        self.generation += 1
        self.loading = False
        self.load_more(reset=True)

    def load_more(self, reset: bool = False) -> None:
        if self.loading:
            return
        offset = 0 if reset else self.results.count()
        if not reset and offset >= self.total:
            return
        self.loading = True
        generation = self.generation
        query = self.search_edit.text().strip()
        color = self.palette().text().color().name()
        self.anki_runner.run(
            lambda: load_page(self.service, query, offset, color),
            lambda page: self.on_page(generation, reset, page),
            lambda _error: self.on_failed(generation),
        )

    def on_page(self, generation: int, reset: bool, page: BrowsePage) -> None:
        if generation != self.generation:
            return
        self.loading = False
        self.total = page.search.total
        if reset:
            self.results.clear()
        for summary, thumbnail in zip(page.search.cards, page.thumbnails, strict=True):
            card = summary.card
            details = " · ".join(part for part in (card.deck_name, " ".join(card.tags)) if part)
            if summary.stale:
                details = f"{details} · {STALE_MARKER}" if details else STALE_MARKER
            item = QListWidgetItem(details)
            pixmap = QPixmap.fromImage(thumbnail)
            icon = QIcon(pixmap)
            icon.addPixmap(pixmap, QIcon.Mode.Selected)
            item.setIcon(icon)
            item.setData(NOTE_ID_ROLE, card.note_id)
            self.results.addItem(item)
        if reset and self.results.count():
            self.results.setCurrentRow(0)
        self.on_scrolled()

    def on_failed(self, generation: int) -> None:
        if generation == self.generation:
            self.loading = False

    def on_scrolled(self, _value: int = 0) -> None:
        scroll_bar = self.results.verticalScrollBar()
        near_end = scroll_bar.maximum() - scroll_bar.value() <= LOAD_MORE_MARGIN * scroll_bar.singleStep()
        if near_end and self.results.count() < self.total:
            self.load_more()

    def on_item_activated(self, item: QListWidgetItem) -> None:
        self.open_requested.emit(int(item.data(NOTE_ID_ROLE)))

    def request_delete(self) -> None:
        item = self.results.currentItem()
        if item is not None:
            self.delete_requested.emit(int(item.data(NOTE_ID_ROLE)))

    def remove_note(self, note_id: int) -> None:
        for row in range(self.results.count()):
            if self.results.item(row).data(NOTE_ID_ROLE) == note_id:
                self.results.takeItem(row)
                self.total -= 1
                return

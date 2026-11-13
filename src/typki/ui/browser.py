from dataclasses import dataclass

from PySide6.QtCore import QByteArray, QEvent, QObject, QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QImage, QKeyEvent, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QWidget,
)

from typki.anki.gateway import AnkiUnavailableError
from typki.card_service import CardService, SearchResult
from typki.render.svg_postprocess import svg_for_display
from typki.ui.background import TaskRunner, debouncer
from typki.ui.layout import page

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


def load_page(service: CardService, query: str, offset: int, limit: int, color: str) -> BrowsePage:
    search = service.search(query, offset=offset, limit=limit)
    thumbnails = tuple(render_thumbnail(summary.card.front_svg, color) for summary in search.cards)
    return BrowsePage(search=search, thumbnails=thumbnails)


DELETE_SHORTCUTS = ("Delete", "Ctrl+Delete", "Backspace")


class BrowserPage(QWidget):
    open_requested = Signal(object)
    delete_requested = Signal(object)
    anki_unreachable = Signal()

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

        page(self, self.search_edit, (self.results, 1))

        self.search_timer = debouncer(self, SEARCH_DEBOUNCE_MS, self.search)
        self.search_edit.textChanged.connect(self.search_timer.start)
        self.search_edit.returnPressed.connect(self.search)
        self.results.itemActivated.connect(self.on_item_activated)
        self.results.verticalScrollBar().valueChanged.connect(self.on_scrolled)
        self.search_edit.installEventFilter(self)
        for sequence in DELETE_SHORTCUTS:
            delete_shortcut = QShortcut(QKeySequence(sequence), self.results)
            delete_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            delete_shortcut.activated.connect(self.request_delete)
        self.results.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.results.customContextMenuRequested.connect(self.show_card_menu)

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

    def search(self) -> None:
        self.search_timer.stop()
        self.generation += 1
        self.request_page(offset=0, limit=PAGE_SIZE, select_note_id=None)

    def reload(self) -> None:
        self.search_timer.stop()
        self.generation += 1
        shown = max(self.results.count(), PAGE_SIZE)
        self.request_page(offset=0, limit=shown, select_note_id=self.current_note_id())

    def load_more(self) -> None:
        if not self.loading and self.results.count() < self.total:
            self.request_page(offset=self.results.count(), limit=PAGE_SIZE, select_note_id=None)

    def request_page(self, offset: int, limit: int, select_note_id: int | None) -> None:
        self.loading = True
        generation = self.generation
        query = self.search_edit.text().strip()
        color = self.palette().text().color().name()
        self.anki_runner.run(
            lambda: load_page(self.service, query, offset, limit, color),
            lambda page: self.on_page(generation, offset, select_note_id, page),
            lambda error: self.on_failed(generation, error),
        )

    def on_page(self, generation: int, offset: int, select_note_id: int | None, page: BrowsePage) -> None:
        if generation != self.generation:
            return
        self.total = page.search.total
        replaces_list = offset == 0
        if replaces_list:
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
        if replaces_list and self.results.count():
            self.results.setCurrentRow(self.row_of(select_note_id) or 0)
        # Only now may scrolling ask for more: clearing a scrolled list moves the scroll bar too.
        self.loading = False
        self.on_scrolled()

    def on_failed(self, generation: int, error: Exception) -> None:
        if generation != self.generation:
            return
        self.loading = False
        if isinstance(error, AnkiUnavailableError):
            self.anki_unreachable.emit()
        else:
            self.anki_runner.default_error(error)

    def current_note_id(self) -> int | None:
        item = self.results.currentItem()
        return int(item.data(NOTE_ID_ROLE)) if item is not None else None

    def row_of(self, note_id: int | None) -> int | None:
        for row in range(self.results.count()):
            if self.results.item(row).data(NOTE_ID_ROLE) == note_id:
                return row
        return None

    def on_scrolled(self, _value: int = 0) -> None:
        scroll_bar = self.results.verticalScrollBar()
        near_end = scroll_bar.maximum() - scroll_bar.value() <= LOAD_MORE_MARGIN * scroll_bar.singleStep()
        if near_end and self.results.count() < self.total:
            self.load_more()

    def on_item_activated(self, item: QListWidgetItem) -> None:
        self.open_requested.emit(int(item.data(NOTE_ID_ROLE)))

    def card_menu_for(self, item: QListWidgetItem) -> QMenu:
        menu = QMenu(self)
        menu.addAction("Open", lambda: self.on_item_activated(item))
        menu.addAction("Delete", self.request_delete)
        return menu

    def show_card_menu(self, position: QPoint) -> None:
        item = self.results.itemAt(position)
        if item is None:
            return
        self.results.setCurrentItem(item)
        self.card_menu_for(item).exec(self.results.viewport().mapToGlobal(position))

    def request_delete(self) -> None:
        note_id = self.current_note_id()
        if note_id is not None and self.confirm_delete():
            self.delete_requested.emit(note_id)

    def confirm_delete(self) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle("Delete card")
        box.setText("Delete this card from Anki?")
        box.setInformativeText("Its review history is deleted with it.")
        delete_button = box.addButton("Delete", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(delete_button)
        box.exec()
        return box.clickedButton() is delete_button

    def remove_note(self, note_id: int) -> None:
        row = self.row_of(note_id)
        if row is not None:
            self.results.takeItem(row)
            self.total -= 1

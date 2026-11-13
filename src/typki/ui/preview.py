from dataclasses import dataclass

from PySide6.QtCore import QByteArray, QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QResizeEvent
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QFrame, QScrollArea, QToolButton, QVBoxLayout, QWidget

from typki.render.svg_postprocess import svg_for_display
from typki.ui.layout import caption_row, filled
from typki.ui.theme import DEFAULT_THEME, Theme

FRONT = "front"
BACK = "back"
CAPTION_GAP = 4
CSS_PIXELS_PER_POINT = 96 / 72
PHONE_WIDTH = 360
PAGE_SIDE_MARGIN = 4
PAGE_BOTTOM_MARGIN = 16
FRAME_RADIUS = 14
FRAME_PADDING_X = 24
FRAME_PADDING_Y = 28
DIVIDER_MARGIN = 22
DIVIDER_THICKNESS = 1
EMPTY_SIDE_HEIGHT = 24
FAILED_OPACITY = 0.35


@dataclass
class Side:
    renderer: QSvgRenderer | None = None
    svg: str = ""
    failed: bool = False

    def size_within(self, width: float) -> QSizeF:
        if self.renderer is None:
            return QSizeF(0, EMPTY_SIDE_HEIGHT)
        natural = self.renderer.viewBoxF().size() * CSS_PIXELS_PER_POINT
        if natural.isEmpty():
            return QSizeF(0, EMPTY_SIDE_HEIGHT)
        return natural * min(1.0, width / natural.width())


class CardCanvas(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.sides = {FRONT: Side(), BACK: Side()}
        self.theme = DEFAULT_THEME
        self.phone = False

    def set_side(self, name: str, svg: str | None, failed: bool) -> None:
        side = self.sides[name]
        side.failed = failed
        if svg is not None:
            side.svg = svg
            self.load(side)
        self.refit()

    def load(self, side: Side) -> None:
        if side.renderer is not None:
            side.renderer.deleteLater()
            side.renderer = None
        if not side.svg:
            return
        renderer = QSvgRenderer(QByteArray(svg_for_display(side.svg, self.theme.text).encode()), self)
        if renderer.isValid():
            side.renderer = renderer
        else:
            renderer.deleteLater()

    def set_theme(self, theme: Theme) -> None:
        self.theme = theme
        for side in self.sides.values():
            self.load(side)
        self.update()

    def set_phone(self, phone: bool) -> None:
        self.phone = phone
        self.refit()

    def content_width(self) -> float:
        available = self.width() - 2 * (PAGE_SIDE_MARGIN + FRAME_PADDING_X)
        return max(min(available, PHONE_WIDTH) if self.phone else available, 1)

    def frame_rect(self) -> QRectF:
        content_width = self.content_width()
        heights = [side.size_within(content_width).height() for side in self.sides.values()]
        height = sum(heights) + 2 * DIVIDER_MARGIN + DIVIDER_THICKNESS + 2 * FRAME_PADDING_Y
        width = content_width + 2 * FRAME_PADDING_X
        return QRectF((self.width() - width) / 2, 0, width, height)

    def refit(self) -> None:
        self.setMinimumHeight(round(self.frame_rect().height()) + PAGE_BOTTOM_MARGIN)
        self.update()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.refit()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(self.theme.chrome))
        frame = self.frame_rect()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self.theme.panel))
        painter.drawRoundedRect(frame, FRAME_RADIUS, FRAME_RADIUS)
        content = frame.adjusted(FRAME_PADDING_X, FRAME_PADDING_Y, -FRAME_PADDING_X, -FRAME_PADDING_Y)
        front_bottom = self.paint_side(painter, self.sides[FRONT], content, content.top())
        divider = QRectF(content.left(), front_bottom + DIVIDER_MARGIN, content.width(), DIVIDER_THICKNESS)
        painter.fillRect(divider, QColor(self.theme.border))
        self.paint_side(painter, self.sides[BACK], content, divider.bottom() + DIVIDER_MARGIN)

    def paint_side(self, painter: QPainter, side: Side, content: QRectF, top: float) -> float:
        size = side.size_within(content.width())
        if side.renderer is not None:
            left = content.left() + (content.width() - size.width()) / 2
            painter.setOpacity(FAILED_OPACITY if side.failed else 1.0)
            side.renderer.render(painter, QRectF(left, top, size.width(), size.height()))
            painter.setOpacity(1.0)
        return top + size.height()


class CardPreview(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.canvas = CardCanvas()
        self.scroll_area = QScrollArea()
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setWidget(self.canvas)
        self.phone_toggle = QToolButton()
        self.phone_toggle.setText("Phone width")
        self.phone_toggle.setCheckable(True)
        self.phone_toggle.toggled.connect(self.canvas.set_phone)

        filled(
            QVBoxLayout(self),
            [caption_row("Preview", self.phone_toggle), (self.scroll_area, 1)],
            spacing=CAPTION_GAP,
        )

    def set_side(self, side: str, svg: str | None, failed: bool) -> None:
        self.canvas.set_side(side, svg, failed)

    def set_theme(self, theme: Theme) -> None:
        self.canvas.set_theme(theme)

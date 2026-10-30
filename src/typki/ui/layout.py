from collections.abc import Iterable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QBoxLayout, QHBoxLayout, QLayout, QSplitter, QVBoxLayout, QWidget

PAGE_MARGINS = (16, 12, 16, 4)
NO_MARGINS = (0, 0, 0, 0)
SPACING = 8
SPLITTER_HANDLE_WIDTH = 16
EQUAL_SPLIT = 100_000

LayoutItem = QWidget | QLayout | tuple[QWidget, int] | int


def filled[BoxLayout: QBoxLayout](
    layout: BoxLayout,
    items: Iterable[LayoutItem],
    spacing: int = SPACING,
    margins: tuple[int, int, int, int] = NO_MARGINS,
) -> BoxLayout:
    layout.setSpacing(spacing)
    layout.setContentsMargins(*margins)
    for item in items:
        if isinstance(item, int):
            layout.addStretch(item)
        elif isinstance(item, tuple):
            layout.addWidget(*item)
        elif isinstance(item, QLayout):
            layout.addLayout(item)
        else:
            layout.addWidget(item)
    return layout


def row(*items: LayoutItem, spacing: int = SPACING) -> QHBoxLayout:
    return filled(QHBoxLayout(), items, spacing)


def column(*items: LayoutItem, spacing: int = SPACING) -> QVBoxLayout:
    return filled(QVBoxLayout(), items, spacing)


def panel(*items: LayoutItem) -> QWidget:
    widget = QWidget()
    widget.setLayout(column(*items))
    return widget


def page(widget: QWidget, *items: LayoutItem) -> None:
    filled(QVBoxLayout(widget), items, margins=PAGE_MARGINS)


def split_page(widget: QWidget, left: QWidget, right: QWidget) -> None:
    splitter = QSplitter(Qt.Orientation.Horizontal)
    splitter.setHandleWidth(SPLITTER_HANDLE_WIDTH)
    for side in (left, right):
        splitter.addWidget(side)
        splitter.setStretchFactor(splitter.indexOf(side), 1)
    splitter.setSizes([EQUAL_SPLIT, EQUAL_SPLIT])
    page(widget, (splitter, 1))

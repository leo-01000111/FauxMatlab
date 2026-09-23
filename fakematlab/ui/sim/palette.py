"""
Block palette: the library, grouped, searchable and draggable onto the canvas.
"""

from __future__ import annotations

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (QLineEdit, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from ...sim.block import by_category
from .canvas import MIME_TYPE

_ROLE = Qt.UserRole + 1


class BlockPalette(QWidget):
    """
    The block library.

    Drag an entry onto the canvas, or double-click to drop one in the middle
    of the view. The filter matches name, category and description, so
    searching "delay" finds ``UnitDelay`` and ``TransportDelay`` as well as the
    Padé note in the description.
    """

    block_chosen = Signal(str)             # type_name, on double-click

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)

        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filter blocks…")
        self._filter.setClearButtonEnabled(True)
        self._filter.textChanged.connect(self._apply_filter)
        layout.addWidget(self._filter)

        self._tree = _DraggableTree()
        self._tree.setHeaderHidden(True)
        self._tree.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self._tree, stretch=1)

        self._populate()

    def _populate(self) -> None:
        self._tree.clear()
        for category, blocks in by_category().items():
            parent = QTreeWidgetItem(self._tree, [category])
            parent.setFlags(Qt.ItemIsEnabled)
            font = parent.font(0)
            font.setBold(True)
            parent.setFont(0, font)
            for cls in blocks:
                child = QTreeWidgetItem(parent, [cls.type_name])
                child.setData(0, _ROLE, cls.type_name)
                child.setToolTip(0, cls.description)
            parent.setExpanded(True)

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        for i in range(self._tree.topLevelItemCount()):
            group = self._tree.topLevelItem(i)
            shown = 0
            for j in range(group.childCount()):
                child = group.child(j)
                haystack = " ".join([
                    child.text(0), group.text(0), child.toolTip(0)]).lower()
                match = needle in haystack
                child.setHidden(not match)
                shown += int(match)
            group.setHidden(shown == 0)
            group.setExpanded(bool(needle) or shown > 0)

    def _on_double_click(self, item: QTreeWidgetItem, _column: int) -> None:
        type_name = item.data(0, _ROLE)
        if type_name:
            self.block_chosen.emit(type_name)


class _DraggableTree(QTreeWidget):
    """Tree whose leaves can be dragged onto the canvas."""

    def startDrag(self, supported_actions) -> None:
        item = self.currentItem()
        type_name = item.data(0, _ROLE) if item else None
        if not type_name:
            return
        mime = QMimeData()
        mime.setData(MIME_TYPE, type_name.encode())
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.CopyAction)

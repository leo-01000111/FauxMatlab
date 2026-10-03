"""
Block palette: the library, grouped, searchable and draggable onto the canvas.
"""

from __future__ import annotations

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QDrag
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QSizePolicy,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...sim.block import by_category
from .. import theme
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
        theme.notifier().changed.connect(self._restyle)

    def _restyle(self, *_args) -> None:
        """Category headers carry a baked foreground; re-read it per theme."""
        muted = QBrush(QColor(theme.tokens().ink_muted))
        for i in range(self._tree.topLevelItemCount()):
            self._tree.topLevelItem(i).setForeground(0, muted)

    def _populate(self) -> None:
        self._tree.clear()
        for category, blocks in by_category().items():
            parent = QTreeWidgetItem(self._tree, [category])
            parent.setFlags(Qt.ItemIsEnabled)
            # Reads like a sign list: mono uppercase category headers,
            # plain UI-font entries beneath.
            parent.setFont(0, theme.label_font(8))
            for cls in blocks:
                child = QTreeWidgetItem(parent, [cls.type_name])
                child.setData(0, _ROLE, cls.type_name)
                child.setToolTip(0, cls.description)
                child.setFont(0, theme.ui_font(10))
            parent.setExpanded(True)
        self._restyle()

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


#: Width of the strip that stays behind when the palette is folded away.
STRIP_WIDTH = 22
#: The palette's widest, matching what the splitter used to cap it at.
EXPANDED_MAX = 280


class PaletteDock(QWidget):
    """
    A :class:`BlockPalette` that can be folded down to a thin strip.

    Once the blocks are placed the library is dead weight: it costs a quarter
    of the canvas's width for nothing. Folding the *whole* palette — rather
    than collapsing its categories, which leaves the search box and the tree
    frame in the way — gives that width back, and the strip that remains is
    one click from bringing it back.
    """

    toggled = Signal(bool)                 # True when collapsed

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.palette = BlockPalette()
        self._collapsed = False

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self.palette, stretch=1)

        self._button = QToolButton()
        self._button.setAutoRaise(True)
        self._button.setFixedWidth(STRIP_WIDTH)
        self._button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self._button.clicked.connect(
            lambda: self.set_collapsed(not self._collapsed))
        row.addWidget(self._button)

        # A preferred width, not a floor: a fixed minimum here once stopped the
        # whole window being narrowed.
        self.setMinimumWidth(0)
        self.setMaximumWidth(EXPANDED_MAX)
        self._refresh()

    @property
    def collapsed(self) -> bool:
        return self._collapsed

    def set_collapsed(self, collapsed: bool) -> None:
        """Fold or unfold the palette; the strip stays either way."""
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        self._refresh()
        self.toggled.emit(collapsed)

    def _refresh(self) -> None:
        self.palette.setVisible(not self._collapsed)
        if self._collapsed:
            self.setMaximumWidth(STRIP_WIDTH)
            self._button.setText("»")
            self._button.setToolTip("Show the block palette (Ctrl+B)")
        else:
            self.setMaximumWidth(EXPANDED_MAX)
            self._button.setText("«")
            self._button.setToolTip("Hide the block palette (Ctrl+B)")


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

"""
The block inspector: parameters with the diagram still visible.

Block parameters used to be a modal dialog on double-click, which meant you
could not see the block you were editing, could not compare two blocks, and
could not change a gain and watch the wire highlighting at the same time.
A modal dialog is the right shape for a decision; it is the wrong shape for
tuning.

The inspector edits the *selected* block and applies through the same undo
command the dialog used, so an edit made here is undoable in the same way and
is validated on a throwaway instance before the live block is touched.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..design import NORMAL, TIGHT, EmptyState, PanelHeader
from .params import ParamForm


class BlockInspector(QWidget):
    """Parameters for whichever block is selected."""

    #: ``(block_id, {name: value})`` — the canvas turns it into an undoable
    #: command, so the inspector never edits a block directly.
    apply_requested = Signal(str, dict)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.block_id: str | None = None
        self._form: ParamForm | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(NORMAL, NORMAL, NORMAL, NORMAL)
        outer.setSpacing(TIGHT)

        self.header = PanelHeader("Properties")
        outer.addWidget(self.header)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(self._scroll, stretch=1)

        self._apply = QPushButton("Apply")
        self._apply.setToolTip("Apply these parameters (undoable)")
        self._apply.clicked.connect(self.commit)
        self._apply.setEnabled(False)
        outer.addWidget(self._apply)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color: palette(mid);")
        outer.addWidget(self._status)

        self.clear()

    # ── contents ────────────────────────────────────────────────

    def clear(self) -> None:
        self.block_id = None
        self._form = None
        self._apply.setEnabled(False)
        self.header.set_subtitle("")
        self._scroll.setWidget(EmptyState(
            "No block selected",
            "Click a block on the canvas to edit its parameters."))
        self._status.clear()

    def show_block(self, block) -> None:
        """Rebuild the form for ``block``."""
        if block is None:
            self.clear()
            return
        self.block_id = block.block_id
        self.header.set_subtitle(f"{block.type_name} · {block.block_id}")
        self._form = ParamForm(block)
        if not block.params_spec:
            self._scroll.setWidget(EmptyState(
                f"{block.type_name} has no parameters",
                block.description))
            self._apply.setEnabled(False)
            return
        self._scroll.setWidget(self._form)
        self._apply.setEnabled(True)
        self._status.clear()

    # ── applying ────────────────────────────────────────────────

    def commit(self) -> bool:
        """Validate and hand the changes to the canvas. True if applied."""
        if self._form is None or self.block_id is None:
            return False
        changes = self._form.commit()
        if changes is None:
            self._status.setText("")
            return False
        if not changes:
            self._status.setText("No changes.")
            return False
        self.apply_requested.emit(self.block_id, changes)
        self._status.setText(
            f"Applied {', '.join(sorted(changes))}.")
        return True

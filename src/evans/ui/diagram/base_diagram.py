"""
Abstract base class for the diagram panel.
==========================================
Defines the interface that the main window and all tabs use to interact
with the block diagram, regardless of whether it's the fixed course
architecture or a future free-form canvas.

Concrete subclasses:
  FixedDiagramView   – the 2-DOF architecture used throughout the course
  FreeDiagramView    – (future) drag-and-drop free-form canvas
"""

from __future__ import annotations

from abc import abstractmethod

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView

from .. import theme


class BaseDiagramView(QGraphicsView):
    """
    Abstract base for all diagram views.

    Signals
    -------
    block_selected(block_id)  – user clicked a block (open its editor)
    signal_selected(sig_id)   – user clicked a signal label (set analysis tap)
    architecture_changed()    – any block TF was updated (recompute analysis)
    """

    block_selected       = Signal(str)   # block_id
    signal_selected      = Signal(str)   # signal_id
    architecture_changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(
            self.renderHints() |
            __import__('PySide6.QtGui', fromlist=['QPainter']).QPainter.Antialiasing
        )
        # A fixed picture: always the whole diagram, fitted to the panel.
        # It is a map of the loop for picking blocks and taps, not a canvas,
        # and zooming or panning it only lost the parts you came to click.
        self.setDragMode(QGraphicsView.NoDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.AnchorViewCenter)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        # Canvas = ground. Items read the tokens at paint time; only this
        # brush is baked in, so restyle it when the theme changes.
        self._restyle()
        theme.notifier().changed.connect(self._restyle)

    def _restyle(self, *_args) -> None:
        self._scene.setBackgroundBrush(QBrush(QColor(theme.tokens().ground)))
        self._scene.update()
        self.viewport().update()

    # ── interface every subclass must implement ─────────────────

    @abstractmethod
    def build(self) -> None:
        """Populate the scene with items."""

    @abstractmethod
    def get_architecture(self):
        """Return the current CourseArchitecture (or equivalent model)."""

    @abstractmethod
    def update_block(self, block_id: str, tf) -> None:
        """Replace a block's TF and redraw if needed."""

    @abstractmethod
    def set_active_signal(self, signal_id: str) -> None:
        """Highlight the active analysis tap."""

    # ── a fixed view: no zoom, no pan, no scroll ────────────────

    def wheelEvent(self, event) -> None:
        # Swallowed, so the wheel neither zooms the diagram nor scrolls
        # whatever holds the panel.
        event.accept()

    def scrollContentsBy(self, dx: int, dy: int) -> None:     # noqa: N802
        # Arrow keys and Page Up/Down scroll a QGraphicsView even with its
        # scroll bars hidden. Only fit_view's own centring may scroll.
        if getattr(self, "_fitting", False):
            super().scrollContentsBy(dx, dy)

    def fit_view(self) -> None:
        """Scale the scene to fill the viewport, with a small margin."""
        rect = self._scene.itemsBoundingRect()
        if rect.isEmpty():
            return
        rect = rect.adjusted(-20, -20, 20, 20)
        self._fitting = True
        try:
            # The scene is exactly what is shown, so there is nothing to
            # scroll to.
            self._scene.setSceneRect(rect)
            self.resetTransform()
            self.fitInView(rect, Qt.KeepAspectRatio)
        finally:
            self._fitting = False

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
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView


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
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)

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

    # ── zoom helpers ────────────────────────────────────────────

    def wheelEvent(self, event) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        self.scale(factor, factor)

    def fit_view(self) -> None:
        """Scale the scene to fill the viewport, with a small margin."""
        rect = self._scene.itemsBoundingRect()
        if rect.isEmpty():
            return
        self.resetTransform()
        self.fitInView(rect.adjusted(-20, -20, 20, 20), Qt.KeepAspectRatio)

    def mouseDoubleClickEvent(self, event) -> None:
        """Double-click anywhere to re-fit after panning or zooming."""
        self.fit_view()
        super().mouseDoubleClickEvent(event)

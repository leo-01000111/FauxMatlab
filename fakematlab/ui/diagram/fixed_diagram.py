"""
Fixed course architecture diagram view (ch.5, slide 16/24).
==========================================================
Renders the 2-DOF block diagram with clickable blocks and signal labels.
Layout (scene units, 1 unit ≈ 1 px at scale 1):

      n(−)
       |
 r → [K1] → ⊕e → [K2] → ⊕u → [G] → ⊕ → y
              ↑(−)        ↑          ↑
             [H] ←────────────────────┘
              ↑di                    ↑do

All positions are hard-coded for a readable fixed layout.
The diagram is read-only in the canvas; editing happens in BlockEditor.
"""

from __future__ import annotations

import control as ctl
from PySide6.QtCore   import QPointF, Qt
from PySide6.QtWidgets import QGraphicsTextItem

from .base_diagram   import BaseDiagramView
from .items          import (DiagramBlock, DiagramSummer, DiagramWire,
                              DiagramSignalLabel, WIRE_COLOR)
from ...core.architecture import CourseArchitecture
from ...core.tf_utils     import unity


# ── Layout constants ──────────────────────────────────────────

# X positions of block centres
X_R   = -480
X_K1  = -360
X_SE  = -240   # summing junction E (error)
X_K2  = -100
X_SU  = 30     # summing junction U (+ di)
X_G   = 160
X_SY  = 300    # summing junction Y (+ do)
X_Y   = 420

# Main signal path Y
Y_MAIN = 0

# Feedback path Y
Y_FEED = 120
X_H    = 0     # H centred under the main path

# Disturbance Y offsets
Y_DI = -90     # di enters from above SU
Y_DO = -90     # do enters from above SY
Y_N  = -60     # n enters from above SY output


class FixedDiagramView(BaseDiagramView):
    """
    Renders the fixed 2-DOF course architecture on a QGraphicsScene.
    """

    def __init__(self, architecture: CourseArchitecture | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self._arch = architecture or CourseArchitecture()
        self._blocks: dict[str, DiagramBlock]   = {}
        self._summers: dict[str, DiagramSummer] = {}
        self._signals: dict[str, DiagramSignalLabel] = {}
        self._active_signal: str | None = None
        self.build()

    # ── BaseDiagramView interface ─────────────────────────────

    def build(self) -> None:
        self._scene.clear()
        self._blocks.clear()
        self._summers.clear()
        self._signals.clear()
        self._draw_blocks()
        self._draw_summers()
        self._draw_wires()
        self._draw_signals()
        self._scene.setSceneRect(self._scene.itemsBoundingRect()
                                 .adjusted(-40, -40, 40, 40))

    def get_architecture(self) -> CourseArchitecture:
        return self._arch

    def update_block(self, block_id: str, tf: ctl.TransferFunction) -> None:
        self._arch.set_block(block_id, tf)
        # Update label tooltip (no visual change needed for fixed diagram)
        self.architecture_changed.emit()

    def set_active_signal(self, signal_id: str) -> None:
        self._active_signal = signal_id
        for sid, item in self._signals.items():
            item.set_active(sid == signal_id)

    # ── Drawing helpers ───────────────────────────────────────

    def _add_block(self, block_id: str, label: str, x: float, y: float):
        block = DiagramBlock(block_id, label)
        block.setPos(x, y)
        self._scene.addItem(block)
        block.clicked.connect(self._on_block_clicked)
        self._blocks[block_id] = block
        return block

    def _add_summer(self, sid: str, x: float, y: float,
                    signs: dict | None = None):
        summer = DiagramSummer(sid, signs)
        summer.setPos(x, y)
        self._scene.addItem(summer)
        self._summers[sid] = summer
        return summer

    def _add_signal(self, signal_id: str, display: str, x: float, y: float):
        label = DiagramSignalLabel(signal_id, display, QPointF(0, 0))
        label.setPos(x, y)
        self._scene.addItem(label)
        label.clicked.connect(self._on_signal_clicked)
        self._signals[signal_id] = label
        return label

    def _wire(self, points: list[tuple[float, float]]):
        wire = DiagramWire([QPointF(x, y) for x, y in points])
        self._scene.addItem(wire)

    # ── Draw blocks ───────────────────────────────────────────

    def _draw_blocks(self):
        self._add_block("K1", "K₁(s)",  X_K1, Y_MAIN)
        self._add_block("K2", "K₂(s)",  X_K2, Y_MAIN)
        self._add_block("G",  "G(s)",   X_G,  Y_MAIN)
        self._add_block("H",  "H(s)",   X_H,  Y_FEED)

    def _draw_summers(self):
        self._add_summer("sum_e", X_SE, Y_MAIN,
                         signs={"left": "+", "bottom": "−"})
        self._add_summer("sum_u", X_SU, Y_MAIN,
                         signs={"left": "+", "top": "+di"})
        self._add_summer("sum_y", X_SY, Y_MAIN,
                         signs={"left": "+", "top": "+do"})

    def _draw_wires(self):
        # r → K1
        self._wire([(X_R, Y_MAIN), (X_K1 - 45, Y_MAIN)])
        # K1 → sum_e
        self._wire([(X_K1 + 45, Y_MAIN), (X_SE - 18, Y_MAIN)])
        # sum_e → K2
        self._wire([(X_SE + 18, Y_MAIN), (X_K2 - 45, Y_MAIN)])
        # K2 → sum_u
        self._wire([(X_K2 + 45, Y_MAIN), (X_SU - 18, Y_MAIN)])
        # sum_u → G
        self._wire([(X_SU + 18, Y_MAIN), (X_G - 45, Y_MAIN)])
        # G → sum_y
        self._wire([(X_G + 45, Y_MAIN), (X_SY - 18, Y_MAIN)])
        # sum_y → y
        self._wire([(X_SY + 18, Y_MAIN), (X_Y, Y_MAIN)])

        # Feedback: y → H → sum_e
        # y branches down at X_SY+18
        branch_x = X_SY + 40
        self._wire([(branch_x, Y_MAIN),
                    (branch_x, Y_FEED),
                    (X_H + 45, Y_FEED)])
        # H → feedback to sum_e
        self._wire([(X_H - 45, Y_FEED),
                    (X_SE, Y_FEED),
                    (X_SE, Y_MAIN + 18)])  # ↑ into bottom of sum_e

        # di from above sum_u
        self._wire([(X_SU, Y_DI), (X_SU, Y_MAIN - 18)])
        # do from above sum_y
        self._wire([(X_SY, Y_DO), (X_SY, Y_MAIN - 18)])
        # n from above, enters feedback before H
        n_x = branch_x + 40
        self._wire([(n_x, Y_N), (n_x, Y_FEED), (X_H + 45, Y_FEED)])

    def _draw_signals(self):
        # Reference
        self._add_signal("r", "r", X_R - 10, Y_MAIN - 14)
        # Error
        self._add_signal("e", "e", (X_SE + X_K2) // 2, Y_MAIN - 16)
        # Control
        self._add_signal("u", "u", (X_SU + X_G) // 2, Y_MAIN - 16)
        # Output
        self._add_signal("y", "y", X_Y + 15, Y_MAIN - 14)
        # Disturbances
        self._add_signal("di", "di", X_SU - 10, Y_DI - 14)
        self._add_signal("do", "do", X_SY - 10, Y_DO - 14)
        self._add_signal("n",  "n",  X_SY + 40, Y_N - 14)

    # ── Slots ─────────────────────────────────────────────────

    def _on_block_clicked(self, block_id: str) -> None:
        # De-select all, select this one
        for bid, item in self._blocks.items():
            item.set_selected(bid == block_id)
        self.block_selected.emit(block_id)

    def _on_signal_clicked(self, signal_id: str) -> None:
        self.set_active_signal(signal_id)
        self.signal_selected.emit(signal_id)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.fit_view()

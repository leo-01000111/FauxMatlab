"""
Scope: plot the signals a run recorded.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .. import theme
from ..plots import add_hline, apply_theme, curve_pen, make_plot, role_colour

#: Above this many samples the display is decimated. The full data is kept for
#: export — only the drawing is thinned, because a pyqtgraph curve of a
#: million points makes panning unusable and shows nothing extra on screen.
MAX_DRAWN = 20_000


class ScopeWidget(QWidget):
    """
    Multi-channel scope with a channel picker and a cursor readout.

    Signals are chosen by name (``block.port``), so the same widget shows a
    Scope block's channels or any other signal the run happened to log.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._result = None
        self._checks: dict[str, QCheckBox] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(2, 2, 2, 2)

        self._plot = make_plot("Scope", "Time (s)", "Amplitude")
        self._plot.getPlotItem().addLegend(offset=(-10, 10))
        root.addWidget(self._plot, stretch=1)

        self._cursor = pg.InfiniteLine(angle=90, movable=True,
                                       pen=pg.mkPen(role_colour("reference"), width=1.2,
                                                    style=Qt.DashLine))
        self._cursor.sigPositionChanged.connect(self._update_readout)

        self._readout = QLabel("")
        self._readout.setTextFormat(Qt.PlainText)
        self._readout.setWordWrap(True)
        self._readout.setFont(theme.data_font(9))      # a readout is data
        root.addWidget(self._readout)

        picker = QScrollArea()
        picker.setWidgetResizable(True)
        picker.setMaximumHeight(96)
        self._picker_body = QWidget()
        self._picker_layout = QHBoxLayout(self._picker_body)
        self._picker_layout.setContentsMargins(4, 2, 4, 2)
        self._picker_layout.addStretch()
        picker.setWidget(self._picker_body)
        root.addWidget(picker)

    # ── data ────────────────────────────────────────────────────

    def show_result(self, result, preferred: list[str] | None = None) -> None:
        """Display a :class:`~fakematlab.sim.solver.SimResult`."""
        self._result = result
        for check in self._checks.values():
            check.setParent(None)
        self._checks.clear()

        names = sorted(result.signals)
        if preferred is None:
            preferred = _default_channels(result, names)

        for name in names:
            check = QCheckBox(name)
            check.setChecked(name in preferred)
            check.stateChanged.connect(self._redraw)
            self._picker_layout.insertWidget(
                self._picker_layout.count() - 1, check)
            self._checks[name] = check
        self._redraw()

    def _redraw(self) -> None:
        plot = self._plot.getPlotItem()
        plot.clear()
        apply_theme(plot, "Scope", "Time (s)", "Amplitude")
        plot.addLegend(offset=(-10, 10))
        if self._result is None:
            return

        t = self._result.t
        stride = max(1, len(t) // MAX_DRAWN)
        drawn = 0
        for name, check in self._checks.items():
            if not check.isChecked():
                continue
            data = self._result.signals[name]
            for channel in range(data.shape[1]):
                label = name if data.shape[1] == 1 else f"{name}[{channel}]"
                plot.plot(t[::stride], data[::stride, channel],
                          pen=curve_pen(drawn, 1.9), name=label)
                drawn += 1

        if drawn:
            add_hline(plot, 0.0, role_colour("muted"), width=0.6)
            plot.addItem(self._cursor)
            self._cursor.setPos(float(t[len(t) // 2]) if len(t) else 0.0)
            self._update_readout()
        else:
            self._readout.setText("")

    def _update_readout(self) -> None:
        if self._result is None or not len(self._result.t):
            return
        x = float(self._cursor.value())
        parts = [f"t = {x:.5g}"]
        for name, check in self._checks.items():
            if not check.isChecked():
                continue
            data = self._result.signals[name]
            for channel in range(data.shape[1]):
                value = float(np.interp(x, self._result.t, data[:, channel]))
                label = name if data.shape[1] == 1 else f"{name}[{channel}]"
                parts.append(f"{label} = {value:.5g}")
        self._readout.setText("   ".join(parts))

    def clear(self) -> None:
        self._result = None
        for check in self._checks.values():
            check.setParent(None)
        self._checks.clear()
        self._plot.getPlotItem().clear()
        self._readout.setText("")


#: The course's own names for the reference and the plant output. A loop drawn
#: the way the lectures draw it has a source ``r`` and a plant ``G``, and the
#: first thing anyone wants to see is how well ``G`` follows ``r``.
REFERENCE_SIGNAL = "r.out"
PLANT_SIGNAL = "G.out"


def _default_channels(result, names: list[str]) -> list[str]:
    """
    What to show when a run finishes.

    The reference and the plant output (``r.out`` and ``G.out``) when the model
    has them: tracking is what a control loop is judged on, and the Scope
    block's own wiring often carries the controller effort instead, which
    dwarfs the response it is meant to explain. If only one of the two exists
    it is still shown alone.

    Otherwise, signals feeding a Scope block if there are any — that is what a
    Scope is for — and failing that the first few signals, so a model without
    a Scope still shows something rather than an empty plot.
    """
    tracking = [n for n in (REFERENCE_SIGNAL, PLANT_SIGNAL) if n in names]
    if tracking:
        return tracking
    wired = [s for sources in result.scopes.values() for s in sources]
    if wired:
        return [n for n in names if n in set(wired)]
    return names[:3]

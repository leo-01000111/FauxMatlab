"""
Renders a :class:`~fakematlab.console.figures.FigureSpec` into a plot widget.

The console's API never touches Qt — it describes a figure and hands the
description to whatever sink is installed. This module is the sink the UI
installs, which is what keeps ``step(G)`` runnable from a headless script and
drawable in the window from the same code.
"""

from __future__ import annotations

import math

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ...console.figures import FigureSpec
from ..plots import (
    add_hline,
    add_marker,
    add_text_annotation,
    add_vline,
    curve_pen,
    freq_vline,
    make_freq_plot,
    make_plot,
    plot_freq,
    role_colour,
)


class FigureView(QWidget):
    """One figure: the widget a ``step`` or ``bode`` call produces."""

    def __init__(self, spec: FigureSpec, parent=None) -> None:
        super().__init__(parent)
        self.spec = spec
        #: Kept by the figure area: the number on the figure's tab, whether it
        #: has been written to disk, and whether a script run (rather than
        #: the prompt) drew it — a script's figures are its output, replaced
        #: by the next run, while a figure typed at the prompt is kept.
        self.number = 0
        self.saved = False
        self.from_script = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        builder = {
            "bode": self._bode,
            "nyquist": self._nyquist,
            "pzmap": self._pzmap,
            "rlocus": self._rlocus,
            "subplot": self._subplots,
        }.get(spec.kind, self._plain)
        builder(layout)

    # ── kinds ───────────────────────────────────────────────────

    def _plain(self, layout) -> None:
        widget = make_plot(self.spec.title, self.spec.xlabel,
                           self.spec.ylabel)
        plot = widget.getPlotItem()
        plot.addLegend(offset=(-10, 10))
        logx = bool(self.spec.extra.get("logx"))
        logy = bool(self.spec.extra.get("logy"))
        for i, trace in enumerate(self.spec.traces):
            x, y = trace.x, trace.y
            if logx or logy:       # a log axis cannot show zero or negatives
                keep = np.ones(len(x), bool)
                if logx:
                    keep &= x > 0
                if logy:
                    keep &= y > 0
                x, y = x[keep], y[keep]
            if trace.style == "scatter":
                plot.plot(x, y, pen=None, symbol="o", symbolSize=6,
                          symbolPen=curve_pen(i, 1.4),
                          name=trace.label or None)
            elif trace.style == "stem":     # a line up from zero to each dot
                plot.plot(np.repeat(x, 2), np.column_stack(
                    [np.zeros_like(y), y]).ravel(), pen=_pen(i, "line"),
                    connect="pairs")
                plot.plot(x, y, pen=None, symbol="o", symbolSize=7,
                          symbolPen=curve_pen(i, 1.4), symbolBrush=None,
                          name=trace.label or None)
            elif trace.style == "bar":
                width = self.spec.extra.get("bar_width", 0.8)
                plot.addItem(pg.BarGraphItem(x=x, height=y, width=width,
                                             pen=curve_pen(i, 1.0),
                                             brush=curve_pen(i, 1.0).color()))
            else:
                plot.plot(x, y, pen=_pen(i, trace.style),
                          name=trace.label or None)
        if logx or logy:
            plot.setLogMode(x=logx, y=logy)
        else:
            add_hline(plot, 0.0, role_colour("muted"), width=0.6)
        _limits(plot, self.spec)
        layout.addWidget(widget)

    def _subplots(self, layout) -> None:
        """``subplot``'s axes, each a figure of its own, on one grid."""
        panes = [p for p in self.spec.extra.get("panes", [])
                 if p["spec"] is not None]
        if self.spec.title:
            layout.addWidget(QLabel(self.spec.title, alignment=Qt.AlignCenter))
        grid = QGridLayout()
        layout.addLayout(grid)
        # Panes from different m×n grids share the least common multiple.
        rows = math.lcm(*(p["rows"] for p in panes)) if panes else 1
        cols = math.lcm(*(p["cols"] for p in panes)) if panes else 1
        for pane in panes:
            m, n = pane["rows"], pane["cols"]
            cells = [c - 1 for c in pane["cells"]]
            r0, r1 = min(c // n for c in cells), max(c // n for c in cells)
            c0, c1 = min(c % n for c in cells), max(c % n for c in cells)
            grid.addWidget(FigureView(pane["spec"]), r0 * rows // m,
                           c0 * cols // n, (r1 - r0 + 1) * rows // m,
                           (c1 - c0 + 1) * cols // n)

    def _bode(self, layout) -> None:
        """Magnitude over phase, sharing one frequency axis."""
        splitter = QSplitter(Qt.Vertical)
        magnitude = make_freq_plot("Bode — Magnitude", "|G| (dB)")
        phase = make_freq_plot("Bode — Phase", "Phase (°)")
        magnitude.setXLink(phase)
        splitter.addWidget(magnitude)
        splitter.addWidget(phase)
        layout.addWidget(splitter)

        mag_plot = magnitude.getPlotItem()
        mag_plot.addLegend(offset=(-10, 10))
        for i, trace in enumerate(self.spec.traces):
            plot_freq(mag_plot, trace.x, trace.y, pen=_pen(i, trace.style),
                      name=trace.label or None)
        add_hline(mag_plot, 0.0, role_colour("muted"), width=0.8)

        phase_plot = phase.getPlotItem()
        for i, (omega, degrees, _label) in enumerate(
                self.spec.extra.get("phase", [])):
            plot_freq(phase_plot, omega, degrees, pen=_pen(i, "line"))
        add_hline(phase_plot, -180.0, role_colour("muted"), width=0.8)

        # The margins are the reason anyone draws a Bode plot; mark them.
        for margins in self.spec.extra.get("margins", []):
            wc = margins.get("wc", float("nan"))
            w180 = margins.get("w180", float("nan"))
            if np.isfinite(wc):
                freq_vline(mag_plot, wc, color=role_colour("reference"),
                           label=f"ωc={wc:.3g}")
                freq_vline(phase_plot, wc, color=role_colour("reference"),
                           label=f"PM={margins.get('pm_deg', float('nan')):.1f}°")
            if np.isfinite(w180) and np.isfinite(margins.get("gm_dB",
                                                             float("inf"))):
                freq_vline(mag_plot, w180, color=role_colour("danger"),
                           label=f"GM={margins['gm_dB']:.2f} dB")

    def _nyquist(self, layout) -> None:
        widget = make_plot(self.spec.title, self.spec.xlabel,
                           self.spec.ylabel)
        plot = widget.getPlotItem()
        plot.setAspectLocked(True)
        plot.addLegend(offset=(-10, 10))
        for i, trace in enumerate(self.spec.traces):
            plot.plot(trace.x, trace.y, pen=_pen(i, trace.style),
                      name=trace.label or None)

        theta = np.linspace(0, 2 * np.pi, 200)
        plot.plot(np.cos(theta), np.sin(theta),
                  pen=_pen(5, "dashed"))
        add_marker(plot, -1.0, 0.0, symbol="x", color=role_colour("danger"), size=14)
        add_text_annotation(plot, -1.0, 0.06, "−1", role_colour("danger"))
        add_hline(plot, 0.0, role_colour("muted"), width=0.6)
        add_vline(plot, 0.0, role_colour("muted"), width=0.6)

        for counts in self.spec.extra.get("counts", []):
            verdict = ("closed loop stable" if counts["Z"] == 0
                       else f"{counts['Z']} unstable CL pole(s)")
            plot.setTitle(
                f"{self.spec.title} — N={counts['N']}, P={counts['P']}, "
                f"Z={counts['Z']} → {verdict}")
        layout.addWidget(widget)

    def _pzmap(self, layout) -> None:
        widget = make_plot(self.spec.title, self.spec.xlabel,
                           self.spec.ylabel)
        plot = widget.getPlotItem()
        plot.addLegend(offset=(-10, 10))
        for i, trace in enumerate(self.spec.traces):
            symbol = "x" if "pole" in trace.label else "o"
            plot.plot(trace.x, trace.y, pen=None, symbol=symbol,
                      symbolSize=13, symbolPen=curve_pen(i, 2.2),
                      name=trace.label or None)
        if self.spec.extra.get("discrete"):
            theta = np.linspace(0, 2 * np.pi, 200)
            plot.plot(np.cos(theta), np.sin(theta), pen=_pen(5, "dashed"))
            plot.setAspectLocked(True)
        add_hline(plot, 0.0, role_colour("muted"), width=0.6)
        add_vline(plot, 0.0, role_colour("muted"), width=0.6)
        _frame(plot, self.spec)
        _limits(plot, self.spec)
        layout.addWidget(widget)

    def _rlocus(self, layout) -> None:
        widget = make_plot(self.spec.title, self.spec.xlabel,
                           self.spec.ylabel)
        plot = widget.getPlotItem()
        for i, trace in enumerate(self.spec.traces):
            plot.plot(trace.x, trace.y, pen=_pen(i, "line"))
        add_hline(plot, 0.0, role_colour("muted"), width=0.6)
        add_vline(plot, 0.0, role_colour("muted"), width=0.6)

        marginal = self.spec.extra.get("K_marginal")
        if marginal is not None and np.isfinite(marginal):
            plot.setTitle(
                f"{self.spec.title} — crosses the imaginary axis at "
                f"K = {marginal:.4g}, ω = "
                f"{self.spec.extra.get('omega_marginal', float('nan')):.4g}")
        _frame(plot, self.spec)
        layout.addWidget(widget)


def _limits(plot, spec: FigureSpec) -> None:
    """Axis limits a script set with ``axis``, ``xlim`` or ``ylim``."""
    xlim = spec.extra.get("xlim")
    ylim = spec.extra.get("ylim")
    if xlim is not None:
        plot.setXRange(float(xlim[0]), float(xlim[1]), padding=0)
    if ylim is not None:
        plot.setYRange(float(ylim[0]), float(ylim[1]), padding=0)


def _frame(plot, spec: FigureSpec) -> None:
    """
    Keep the imaginary axis from autoscaling to round-off.

    A set of real poles comes back from ``np.roots`` with imaginary parts
    around 1e-6; autoscaling to those makes coincident poles look spread out.
    """
    xs = np.concatenate([t.x for t in spec.traces]) if spec.traces else None
    ys = np.concatenate([t.y for t in spec.traces]) if spec.traces else None
    if xs is None or not len(xs):
        return
    x_lo, x_hi = float(np.min(xs)), float(np.max(xs))
    span = max(x_hi - x_lo, 1e-9)
    y_span = max(float(np.max(np.abs(ys))) if len(ys) else 0.0, 0.25 * span)
    plot.setXRange(x_lo - 0.15 * span, x_hi + 0.15 * span, padding=0)
    plot.setYRange(-y_span * 1.15, y_span * 1.15, padding=0)


def _pen(index: int, style: str):
    from PySide6.QtCore import Qt as _Qt

    pen = curve_pen(index, 2.0 if style == "line" else 1.4)
    if style == "dashed":
        pen.setStyle(_Qt.DashLine)
    return pen

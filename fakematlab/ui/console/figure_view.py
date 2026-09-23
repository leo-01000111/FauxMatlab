"""
Renders a :class:`~fakematlab.console.figures.FigureSpec` into a plot widget.

The console's API never touches Qt — it describes a figure and hands the
description to whatever sink is installed. This module is the sink the UI
installs, which is what keeps ``step(G)`` runnable from a headless script and
drawable in the window from the same code.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSplitter, QVBoxLayout, QWidget

from ...console.figures import FigureSpec
from ..plots import (add_hline, add_marker, add_text_annotation, add_vline,
                     curve_pen, freq_vline, make_freq_plot, make_plot,
                     plot_freq)


class FigureView(QWidget):
    """One figure: the widget a ``step`` or ``bode`` call produces."""

    def __init__(self, spec: FigureSpec, parent=None) -> None:
        super().__init__(parent)
        self.spec = spec
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        builder = {
            "bode": self._bode,
            "nyquist": self._nyquist,
            "pzmap": self._pzmap,
            "rlocus": self._rlocus,
        }.get(spec.kind, self._plain)
        builder(layout)

    # ── kinds ───────────────────────────────────────────────────

    def _plain(self, layout) -> None:
        widget = make_plot(self.spec.title, self.spec.xlabel,
                           self.spec.ylabel)
        plot = widget.getPlotItem()
        plot.addLegend(offset=(-10, 10))
        for i, trace in enumerate(self.spec.traces):
            plot.plot(trace.x, trace.y, pen=_pen(i, trace.style),
                      name=trace.label or None)
        add_hline(plot, 0.0, "#888888", width=0.6)
        layout.addWidget(widget)

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
        add_hline(mag_plot, 0.0, "#888888", width=0.8)

        phase_plot = phase.getPlotItem()
        for i, (omega, degrees, label) in enumerate(
                self.spec.extra.get("phase", [])):
            plot_freq(phase_plot, omega, degrees, pen=_pen(i, "line"))
        add_hline(phase_plot, -180.0, "#888888", width=0.8)

        # The margins are the reason anyone draws a Bode plot; mark them.
        for margins in self.spec.extra.get("margins", []):
            wc = margins.get("wc", float("nan"))
            w180 = margins.get("w180", float("nan"))
            if np.isfinite(wc):
                freq_vline(mag_plot, wc, color="#F4A261",
                           label=f"ωc={wc:.3g}")
                freq_vline(phase_plot, wc, color="#F4A261",
                           label=f"PM={margins.get('pm_deg', float('nan')):.1f}°")
            if np.isfinite(w180) and np.isfinite(margins.get("gm_dB",
                                                             float("inf"))):
                freq_vline(mag_plot, w180, color="#F45B69",
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
        add_marker(plot, -1.0, 0.0, symbol="x", color="#FF4444", size=14)
        add_text_annotation(plot, -1.0, 0.06, "−1", "#FF4444")
        add_hline(plot, 0.0, "#888888", width=0.6)
        add_vline(plot, 0.0, "#888888", width=0.6)

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
        add_hline(plot, 0.0, "#888888", width=0.6)
        add_vline(plot, 0.0, "#888888", width=0.6)
        _frame(plot, self.spec)
        layout.addWidget(widget)

    def _rlocus(self, layout) -> None:
        widget = make_plot(self.spec.title, self.spec.xlabel,
                           self.spec.ylabel)
        plot = widget.getPlotItem()
        for i, trace in enumerate(self.spec.traces):
            plot.plot(trace.x, trace.y, pen=_pen(i, "line"))
        add_hline(plot, 0.0, "#888888", width=0.6)
        add_vline(plot, 0.0, "#888888", width=0.6)

        marginal = self.spec.extra.get("K_marginal")
        if marginal is not None and np.isfinite(marginal):
            plot.setTitle(
                f"{self.spec.title} — crosses the imaginary axis at "
                f"K = {marginal:.4g}, ω = "
                f"{self.spec.extra.get('omega_marginal', float('nan')):.4g}")
        _frame(plot, self.spec)
        layout.addWidget(widget)


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

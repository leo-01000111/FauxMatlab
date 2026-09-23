"""
Structure view: controllability, observability, Gramians, model reduction.
"""

from __future__ import annotations

import control as ctl
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QPushButton,
                               QSpinBox, QSplitter, QVBoxLayout, QWidget)

from ....core.statespace import StateSpaceError
from ....core.structural import (analyse_structure, balanced_reduction,
                                  hankel_singular_values, kalman_decomposition,
                                  reduction_error_bound)
from ...guard import GuardedPanel, guard
from ...plots import (apply_theme, curve_pen, make_freq_plot, make_plot,
                       plot_freq)
from .widgets import fill_table, make_table


class StructureView(QWidget, GuardedPanel):
    """Can every mode be reached, and can every mode be seen?"""

    def __init__(self, context, parent=None) -> None:
        super().__init__(parent)
        self.ctx = context
        self._build_ui()
        self.ctx.model_changed.connect(self.refresh)
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(2, 2, 2, 2)
        self.install_error_banner(root)

        splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        left.setMaximumWidth(430)
        left_lay = QVBoxLayout(left)

        verdict = QGroupBox("Verdict")
        verdict_lay = QVBoxLayout(verdict)
        self._verdict = QLabel("")
        self._verdict.setWordWrap(True)
        self._verdict.setFont(QFont("Consolas", 9))
        self._verdict.setTextInteractionFlags(Qt.TextSelectableByMouse)
        verdict_lay.addWidget(self._verdict)
        left_lay.addWidget(verdict)

        kalman = QGroupBox("Kalman decomposition")
        kalman_lay = QVBoxLayout(kalman)
        self._kalman = QLabel("")
        self._kalman.setFont(QFont("Consolas", 9))
        self._kalman.setWordWrap(True)
        kalman_lay.addWidget(self._kalman)
        left_lay.addWidget(kalman)

        reduce_box = QGroupBox("Balanced reduction")
        reduce_lay = QVBoxLayout(reduce_box)
        row = QHBoxLayout()
        row.addWidget(QLabel("Keep states:"))
        self._order = QSpinBox()
        self._order.setRange(1, 64)
        self._order.setValue(1)
        self._order.valueChanged.connect(self._reduce)
        row.addWidget(self._order)
        apply_min = QPushButton("Use reduced model")
        apply_min.clicked.connect(self._adopt)
        row.addWidget(apply_min)
        reduce_lay.addLayout(row)
        self._reduce_note = QLabel("")
        self._reduce_note.setWordWrap(True)
        reduce_lay.addWidget(self._reduce_note)
        left_lay.addWidget(reduce_box)
        left_lay.addStretch()
        splitter.addWidget(left)

        right = QSplitter(Qt.Vertical)

        mode_box = QGroupBox("PBH test, one mode at a time")
        mode_lay = QVBoxLayout(mode_box)
        self._modes = make_table(
            ["λ", "stable?", "controllable?", "observable?", "verdict"])
        mode_lay.addWidget(self._modes)
        right.addWidget(mode_box)

        plots = QWidget()
        plot_lay = QHBoxLayout(plots)
        self._hankel = make_plot("Hankel singular values",
                                 "state index", "σ")
        plot_lay.addWidget(self._hankel)
        self._compare = make_freq_plot("Full vs reduced", "|G| (dB)")
        plot_lay.addWidget(self._compare)
        right.addWidget(plots)

        right.setStretchFactor(0, 1)
        right.setStretchFactor(1, 2)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, stretch=1)

    # ── refresh ─────────────────────────────────────────────────

    @guard("Structural analysis")
    def refresh(self, *_ignored) -> None:
        sys = self.ctx.sys
        report = analyse_structure(sys)
        self._verdict.setText(report.summary())
        self._kalman.setText(kalman_decomposition(sys).summary())

        fill_table(self._modes, [
            [_fmt_complex(m.eigenvalue),
             "yes" if m.stable else "NO",
             "yes" if m.controllable else "NO",
             "yes" if m.observable else "NO",
             "fatal — unstable and hidden" if m.fatal
             else ("fine" if m.controllable and m.observable else "hidden")]
            for m in report.modes
        ])

        self._order.blockSignals(True)
        self._order.setMaximum(max(sys.nstates, 1))
        self._order.setValue(max(min(self._order.value(), sys.nstates), 1))
        self._order.blockSignals(False)
        self._reduce()

    @guard("Balanced reduction")
    def _reduce(self, *_ignored) -> None:
        sys = self.ctx.sys
        hankel = self._hankel.getPlotItem()
        hankel.clear()
        apply_theme(hankel, "Hankel singular values", "state index", "σ")
        compare = self._compare.getPlotItem()
        compare.clear()
        apply_theme(compare, "Full vs reduced", "ω (rad/s)", "|G| (dB)")
        compare.addLegend(offset=(-10, 10))

        try:
            sigma = hankel_singular_values(sys)
        except StateSpaceError as exc:
            self._reduce_note.setText(f"⚠ {exc}")
            return

        index = np.arange(1, len(sigma) + 1)
        hankel.plot(index, sigma, pen=curve_pen(0, 2.0),
                    symbol="o", symbolSize=7)
        hankel.setLogMode(x=False, y=True)

        order = int(self._order.value())
        if order >= sys.nstates:
            self._reduce_note.setText(
                "keeping every state — lower the order to see what reduction "
                "costs")
            return

        try:
            reduced, sigma = balanced_reduction(sys, order)
        except StateSpaceError as exc:
            # Reduction needs a minimal realisation; say which button fixes it.
            self._reduce_note.setText(
                f"⚠ {exc}\nUse “Minimal realisation” on the State Space tab "
                f"first.")
            return

        self._reduced = reduced
        bound = reduction_error_bound(sigma, order)

        w = _grid(sys)
        full_dB = 20 * np.log10(np.maximum(
            np.squeeze(ctl.frequency_response(sys, w).magnitude), 1e-300))
        red_dB = 20 * np.log10(np.maximum(
            np.squeeze(ctl.frequency_response(reduced, w).magnitude), 1e-300))
        plot_freq(compare, w, full_dB, pen=curve_pen(0, 2.0),
                  name=f"full ({sys.nstates} states)")
        plot_freq(compare, w, red_dB, pen=curve_pen(1, 1.8),
                  name=f"reduced ({order} states)")

        actual = float(np.max(np.abs(
            np.squeeze(ctl.frequency_response(sys, w).magnitude) -
            np.squeeze(ctl.frequency_response(reduced, w).magnitude))))
        self._reduce_note.setText(
            f"{sys.nstates} → {order} states\n"
            f"actual ‖G − Gᵣ‖∞ ≈ {actual:.4g}\n"
            f"guaranteed bound 2·Σσ = {bound:.4g}")

    @guard("Adopt reduced model")
    def _adopt(self) -> None:
        reduced = getattr(self, "_reduced", None)
        if reduced is None or reduced.nstates >= self.ctx.sys.nstates:
            self.ctx.status.emit("nothing to adopt — lower the order first")
            return
        self.ctx.set_system(reduced, f"balanced reduction to "
                                     f"{reduced.nstates} states")


def _grid(sys) -> np.ndarray:
    poles = np.atleast_1d(ctl.poles(sys))
    scale = max((abs(p) for p in poles if abs(p) > 1e-9), default=1.0)
    return np.logspace(np.log10(scale) - 3, np.log10(scale) + 2, 400)


def _fmt_complex(z: complex) -> str:
    if abs(z.imag) < 1e-10:
        return f"{z.real:.5g}"
    sign = "+" if z.imag >= 0 else "−"
    return f"{z.real:.4g} {sign} {abs(z.imag):.4g}j"

"""
Discrete view: sampling, the unit circle, Jury, deadbeat, sample-rate effects.
"""

from __future__ import annotations

import control as ctl
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ....core.discrete import (
    DiscreteError,
    c2d,
    compare_methods,
    d2c,
    damping_from_z,
    deadbeat,
    jury_from_system,
    sample_rate_sweep,
    settling_samples,
    unit_circle,
)
from ...guard import GuardedPanel, guard
from ...plots import (
    add_hline,
    add_vline,
    apply_theme,
    curve_pen,
    make_freq_plot,
    make_plot,
    plot_freq,
)
from .widgets import fill_table, make_table


class DiscreteView(QWidget, GuardedPanel):
    """What sampling does to a design."""

    def __init__(self, context, parent=None) -> None:
        super().__init__(parent)
        self.ctx = context
        self._discrete = None
        self._build_ui()
        self.ctx.model_changed.connect(self.refresh)
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(2, 2, 2, 2)
        self.install_error_banner(root)

        splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        left.setMaximumWidth(380)
        left_lay = QVBoxLayout(left)

        sample_box = QGroupBox("Sampling")
        sample_lay = QVBoxLayout(sample_box)
        row = QHBoxLayout()
        row.addWidget(QLabel("Ts:"))
        self._dt = QDoubleSpinBox()
        self._dt.setRange(1e-4, 100.0)
        self._dt.setDecimals(4)
        self._dt.setValue(0.1)
        self._dt.setSingleStep(0.01)
        self._dt.valueChanged.connect(self.refresh)
        row.addWidget(self._dt)
        row.addWidget(QLabel("Method:"))
        self._method = QComboBox()
        self._method.addItems(["zoh", "tustin", "euler", "backward_diff",
                               "matched"])
        self._method.currentIndexChanged.connect(self.refresh)
        row.addWidget(self._method)
        sample_lay.addLayout(row)
        self._nyquist = QLabel("")
        sample_lay.addWidget(self._nyquist)

        back = QPushButton("d2c — recover the continuous model")
        back.setToolTip(
            "python-control has no d2c; this inverts the sampling exactly for "
            "ZOH, where an exact inverse exists.")
        back.clicked.connect(self._d2c)
        sample_lay.addWidget(back)
        left_lay.addWidget(sample_box)

        dead_box = QGroupBox("Deadbeat control")
        dead_lay = QVBoxLayout(dead_box)
        dead_lay.addWidget(QLabel(
            "Every pole at z = 0: the state reaches zero exactly after n\n"
            "samples. No continuous design can do this — and nothing is left\n"
            "in reserve, so it is as fragile as it is fast."))
        dead_button = QPushButton("Design deadbeat")
        dead_button.clicked.connect(self._deadbeat)
        dead_lay.addWidget(dead_button)
        self._dead_result = QLabel("")
        self._dead_result.setWordWrap(True)
        self._dead_result.setFont(QFont("Consolas", 9))
        dead_lay.addWidget(self._dead_result)
        left_lay.addWidget(dead_box)

        jury_box = QGroupBox("Jury criterion")
        jury_lay = QVBoxLayout(jury_box)
        self._jury = QLabel("")
        self._jury.setWordWrap(True)
        self._jury.setFont(QFont("Consolas", 9))
        self._jury.setTextInteractionFlags(Qt.TextSelectableByMouse)
        jury_lay.addWidget(self._jury)
        left_lay.addWidget(jury_box)
        left_lay.addStretch()
        splitter.addWidget(left)

        right = QSplitter(Qt.Vertical)

        pole_box = QGroupBox("Discrete poles")
        pole_lay = QVBoxLayout(pole_box)
        self._poles = make_table(["z", "|z|", "inside?", "ζ", "ωn (rad/s)"],
                                 max_height=170)
        pole_lay.addWidget(self._poles)
        right.addWidget(pole_box)

        plots = QWidget()
        plot_lay = QHBoxLayout(plots)
        self._zplane = make_plot("z-plane", "Re", "Im")
        self._zplane.getPlotItem().setAspectLocked(True)
        plot_lay.addWidget(self._zplane)
        self._methods = make_freq_plot("Discretisation methods compared",
                                       "|G| (dB)")
        plot_lay.addWidget(self._methods)
        right.addWidget(plots)

        sweep_box = QGroupBox("Sample-rate sweep")
        sweep_lay = QVBoxLayout(sweep_box)
        self._sweep = make_table(
            ["Ts", "Nyquist (rad/s)", "ZOH lag at ωc", "max |z|", "stable?"],
            max_height=180)
        sweep_lay.addWidget(self._sweep)
        right.addWidget(sweep_box)

        right.setStretchFactor(1, 2)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, stretch=1)

    # ── refresh ─────────────────────────────────────────────────

    @guard("Discretisation")
    def refresh(self, *_ignored) -> None:
        # Qt's valueChanged/currentIndexChanged pass the new value, while
        # model_changed passes nothing; accepting and discarding whatever
        # arrives keeps one slot usable from all three.
        dt = float(self._dt.value())
        method = self._method.currentText()
        self._discrete = c2d(self.ctx.sys, dt, method)
        self._nyquist.setText(
            f"Nyquist frequency = π/Ts = {np.pi / dt:.4g} rad/s — anything "
            f"faster aliases down.")

        self._fill_poles(dt)
        self._draw_zplane()
        self._draw_methods(dt)
        self._fill_sweep()
        self._show_jury()

    def _fill_poles(self, dt: float) -> None:
        poles = np.atleast_1d(ctl.poles(self._discrete))
        rows = []
        for z in poles:
            zeta, wn = damping_from_z(complex(z), dt)
            rows.append([
                _fmt_complex(complex(z)), f"{abs(z):.5f}",
                "yes" if abs(z) < 1.0 else "NO",
                "—" if np.isnan(zeta) else f"{zeta:.4g}",
                "∞" if np.isinf(wn) else f"{wn:.4g}",
            ])
        fill_table(self._poles, rows)

    def _draw_zplane(self) -> None:
        plot = self._zplane.getPlotItem()
        plot.clear()
        apply_theme(plot, "z-plane", "Re", "Im")
        cx, cy = unit_circle()
        plot.plot(cx, cy, pen=curve_pen(5, 1.2))
        add_hline(plot, 0.0, "#888888", width=0.6)
        add_vline(plot, 0.0, "#888888", width=0.6)

        poles = np.atleast_1d(ctl.poles(self._discrete))
        plot.plot([z.real for z in poles], [z.imag for z in poles],
                  pen=None, symbol="x", symbolSize=13,
                  symbolPen=curve_pen(1, 2.4))
        zeros = np.atleast_1d(ctl.zeros(self._discrete))
        if len(zeros):
            plot.plot([z.real for z in zeros], [z.imag for z in zeros],
                      pen=None, symbol="o", symbolSize=11,
                      symbolPen=curve_pen(0, 2.0))

    def _draw_methods(self, dt: float) -> None:
        plot = self._methods.getPlotItem()
        plot.clear()
        apply_theme(plot, "Discretisation methods compared",
                    "ω (rad/s)", "|G| (dB)")
        plot.addLegend(offset=(-10, 10))

        nyquist = np.pi / dt
        w = np.logspace(np.log10(nyquist) - 3, np.log10(nyquist), 400)
        continuous = 20 * np.log10(np.maximum(
            np.squeeze(ctl.frequency_response(self.ctx.sys, w).magnitude),
            1e-300))
        plot_freq(plot, w, continuous, pen=curve_pen(0, 2.2),
                  name="continuous")

        for i, (name, sampled) in enumerate(
                compare_methods(self.ctx.sys, dt).items()):
            try:
                mag = np.squeeze(
                    ctl.frequency_response(sampled, w).magnitude)
            except Exception:                          # noqa: BLE001
                continue
            plot_freq(plot, w, 20 * np.log10(np.maximum(mag, 1e-300)),
                      pen=curve_pen(i + 1, 1.5), name=name)

        # The methods agree at low frequency and diverge near Nyquist, which
        # is the whole point of the comparison.
        from ...plots import freq_vline
        freq_vline(plot, nyquist, color="#F45B69", label="Nyquist")

    def _fill_sweep(self) -> None:
        poles = np.atleast_1d(ctl.poles(self.ctx.sys))
        scale = max((abs(p) for p in poles if abs(p) > 1e-9), default=1.0)
        rates = [r / scale for r in (0.02, 0.05, 0.1, 0.3, 0.6, 1.2, 2.5)]

        rows = []
        for dt, info in sample_rate_sweep(self.ctx.sys, rates).items():
            if "error" in info:
                rows.append([f"{dt:.4g}", "—", "—", "—", info["error"][:40]])
                continue
            lag = info["phase_lag_at_wc_deg"]
            rows.append([
                f"{dt:.4g}", f"{info['nyquist']:.4g}",
                "—" if np.isnan(lag) else f"{lag:.1f}°",
                f"{info['max_magnitude']:.4f}",
                "yes" if info["stable"] else "NO",
            ])
        fill_table(self._sweep, rows)

    def _show_jury(self) -> None:
        try:
            result = jury_from_system(self._discrete)
        except DiscreteError as exc:
            self._jury.setText(f"⚠ {exc}")
            return
        self._jury.setText(result.summary())

    # ── actions ─────────────────────────────────────────────────

    @guard("Deadbeat design")
    def _deadbeat(self) -> None:
        K = deadbeat(self._discrete)
        samples = settling_samples(self._discrete, K)
        dt = float(self._dt.value())
        self._dead_result.setText(
            f"K = {np.array2string(K.ravel(), precision=4)}\n"
            f"settles in {samples} samples = {samples * dt:.4g} s\n"
            f"|u(0)| ≈ {float(np.max(np.abs(K))):.4g} per unit of state — "
            f"that is the price.")
        self.ctx.set_feedback(K)

    @guard("d2c")
    def _d2c(self) -> None:
        method = "tustin" if self._method.currentText() in (
            "tustin", "bilinear") else "zoh"
        recovered = d2c(self._discrete, method)
        self.ctx.set_system(recovered,
                            f"d2c ({method}) of the sampled model")
        self.ctx.status.emit(
            f"recovered a continuous model from the {method} sampling")


def _fmt_complex(z: complex) -> str:
    if abs(z.imag) < 1e-10:
        return f"{z.real:.5g}"
    sign = "+" if z.imag >= 0 else "−"
    return f"{z.real:.4g} {sign} {abs(z.imag):.4g}j"

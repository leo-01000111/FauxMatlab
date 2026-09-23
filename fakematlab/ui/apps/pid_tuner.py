"""
The PID Tuner — two sliders, and an honest account of what they do.

MATLAB's tuner hides the meaning of its sliders. This one prints it: the
response-time slider sets the target crossover frequency, the transient slider
sets the target phase margin, and the readout says which values were asked for
and which were achieved. When a target is impossible, the banner says why
rather than quietly returning gains that do something else.
"""

from __future__ import annotations

import control as ctl
import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QPushButton,
                               QSlider, QSplitter, QTextEdit, QVBoxLayout,
                               QWidget)

from ...core.pidtune import (PIDKind, TuneResult, crossover_for,
                             phase_margin_for, tune)
from ...core.timeresp import step_response
from ..guard import GuardedPanel, guard
from ..plots import (add_hline, curve_pen, freq_vline, make_freq_plot,
                     make_plot, plot_freq)

#: Slider travel. Both run over integers so the widget behaves; the mapping to
#: physical quantities lives in :mod:`fakematlab.core.pidtune`.
SPEED_TICKS = 100          # −100 … +100  ⇒  speed −1 … +1
TRANSIENT_TICKS = 100      # 0 … 100      ⇒  transient 0 … 1


class PIDTuner(QWidget, GuardedPanel):
    """Tune a PID for a plant, and compare it against what is there now."""

    #: The user pressed "Apply as K₂".
    controller_applied = Signal(object)          # TransferFunction

    def __init__(self, plant: ctl.TransferFunction | None = None,
                 baseline: ctl.TransferFunction | None = None,
                 kind: PIDKind | str = PIDKind.PI, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("PID Tuner")
        self.resize(1050, 700)
        self._plant = plant if plant is not None else ctl.tf([1], [1, 3, 3, 1])
        self._baseline = baseline
        self.result: TuneResult | None = None
        self._build_ui()
        self._kind_combo.setCurrentText(PIDKind(kind).value)
        self.retune()

    # ── UI ──────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        self.install_error_banner(outer)

        split = QSplitter(Qt.Horizontal)
        outer.addWidget(split, stretch=1)
        split.addWidget(self._build_controls())
        split.addWidget(self._build_plots())
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)

    def _build_controls(self) -> QWidget:
        panel = QWidget()
        panel.setMaximumWidth(340)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)

        form = QFormLayout()
        self._kind_combo = QComboBox()
        self._kind_combo.addItems([k.value for k in PIDKind])
        self._kind_combo.currentIndexChanged.connect(self.retune)
        form.addRow("Controller:", self._kind_combo)

        self._tf_spin = QDoubleSpinBox()
        self._tf_spin.setRange(0.0, 10.0)
        self._tf_spin.setDecimals(4)
        self._tf_spin.setSingleStep(0.01)
        self._tf_spin.setToolTip(
            "Derivative filter time constant. Applied after the gains are "
            "solved, so it shifts the achieved margin slightly.")
        self._tf_spin.valueChanged.connect(self.retune)
        form.addRow("Tf (D filter):", self._tf_spin)
        lay.addLayout(form)

        # ── the two sliders ──
        slider_box = QGroupBox("Design targets")
        slider_lay = QVBoxLayout(slider_box)

        self._speed_label = QLabel()
        slider_lay.addWidget(self._speed_label)
        self._speed = QSlider(Qt.Horizontal)
        self._speed.setRange(-SPEED_TICKS, SPEED_TICKS)
        self._speed.setValue(0)
        self._speed.valueChanged.connect(self.retune)
        slider_lay.addWidget(self._speed)
        slider_lay.addWidget(_ends("slower", "faster"))

        self._transient_label = QLabel()
        slider_lay.addWidget(self._transient_label)
        self._transient = QSlider(Qt.Horizontal)
        self._transient.setRange(0, TRANSIENT_TICKS)
        self._transient.setValue(TRANSIENT_TICKS // 2)
        self._transient.valueChanged.connect(self.retune)
        slider_lay.addWidget(self._transient)
        slider_lay.addWidget(_ends("aggressive", "robust"))
        lay.addWidget(slider_box)

        self._readout = QTextEdit()
        self._readout.setReadOnly(True)
        self._readout.setFont(QFont("Consolas", 9))
        lay.addWidget(self._readout, stretch=1)

        buttons = QHBoxLayout()
        reset = QPushButton("Reset sliders")
        reset.clicked.connect(self.reset)
        buttons.addWidget(reset)
        apply_btn = QPushButton("Apply as K₂")
        apply_btn.clicked.connect(self._apply)
        buttons.addWidget(apply_btn)
        lay.addLayout(buttons)
        return panel

    def _build_plots(self) -> QWidget:
        split = QSplitter(Qt.Vertical)
        self._step_widget = make_plot("Closed-loop step response",
                                      "Time (s)", "y(t)")
        self._bode_widget = make_freq_plot("Open loop L(s) = C·G", "|L| (dB)")
        split.addWidget(self._step_widget)
        split.addWidget(self._bode_widget)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        return split

    # ── state ───────────────────────────────────────────────────

    def set_plant(self, plant: ctl.TransferFunction,
                  baseline: ctl.TransferFunction | None = None) -> None:
        self._plant = plant
        self._baseline = baseline
        self.retune()

    @property
    def kind(self) -> PIDKind:
        return PIDKind(self._kind_combo.currentText())

    @property
    def speed(self) -> float:
        return self._speed.value() / SPEED_TICKS

    @property
    def transient(self) -> float:
        return self._transient.value() / TRANSIENT_TICKS

    def reset(self) -> None:
        self._speed.setValue(0)
        self._transient.setValue(TRANSIENT_TICKS // 2)

    def _apply(self) -> None:
        if self.result is not None and self.result.feasible:
            self.controller_applied.emit(self.result.C)

    # ── tuning ──────────────────────────────────────────────────

    @guard("PID tuner")
    def retune(self, *_ignored) -> None:
        pm = phase_margin_for(self.transient)
        wc = crossover_for(self._plant, self.speed, pm, self.kind)
        self._speed_label.setText(
            f"Response time — target ωc = {wc:.4g} rad/s "
            f"(≈ {2.0 / wc:.3g} s)")
        self._transient_label.setText(
            f"Transient behaviour — target phase margin = {pm:.1f}°")

        result = tune(self._plant, self.kind, wc=wc, pm_deg=pm,
                      Tf=float(self._tf_spin.value()))
        self.result = result
        self._readout.setPlainText(result.describe())
        self._draw(result)
        if not result.feasible:
            # Not an exception: an impossible target is a legitimate answer,
            # and the reason is already on screen. Raising here would bury a
            # clear explanation under a traceback.
            self._readout.setPlainText(
                f"{result.describe()}\n\n"
                f"Move the response-time slider and the target moves with it.")

    def _draw(self, result: TuneResult) -> None:
        self._draw_step(result)
        self._draw_bode(result)

    def _draw_step(self, result: TuneResult) -> None:
        plot = self._step_widget.getPlotItem()
        plot.clear()
        plot.addLegend(offset=(-10, 10))

        curves: list[tuple[str, ctl.TransferFunction, int]] = []
        if self._baseline is not None:
            curves.append(("before", ctl.feedback(self._baseline * self._plant,
                                                  1), 1))
        if result.feasible and result.stable:
            curves.append((f"after ({result.kind.value})", result.T, 0))

        for label, system, colour in curves:
            try:
                resp = step_response(system)
            except Exception:                                   # noqa: BLE001
                continue
            y = np.atleast_2d(resp.y)[0]
            plot.plot(resp.t, y, pen=curve_pen(colour, 2.0), name=label)

        add_hline(plot, 1.0, "#888888", width=0.8)
        if not curves:
            plot.setTitle("Nothing stable to show at this target")
        else:
            plot.setTitle("Closed-loop step response")

    def _draw_bode(self, result: TuneResult) -> None:
        from ...core.freqresp import bode as _bode

        plot = self._bode_widget.getPlotItem()
        plot.clear()
        plot.addLegend(offset=(-10, 10))

        loops: list[tuple[str, ctl.TransferFunction, int]] = [
            ("plant G", self._plant, 2)]
        if self._baseline is not None:
            loops.append(("before", self._baseline * self._plant, 1))
        if result.feasible:
            loops.append(("after", result.L, 0))

        for label, system, colour in loops:
            bd = _bode(system)
            plot_freq(plot, bd.omega, bd.mag_dB, pen=curve_pen(colour, 2.0),
                      name=label)
        add_hline(plot, 0.0, "#888888", width=0.8)
        if result.feasible and np.isfinite(result.achieved_wc):
            freq_vline(plot, result.achieved_wc, color="#F4A261",
                       label=f"ωc {result.achieved_wc:.3g}")


def _ends(left: str, right: str) -> QWidget:
    """The two end-labels under a slider."""
    widget = QWidget()
    row = QHBoxLayout(widget)
    row.setContentsMargins(0, 0, 0, 0)
    for text, align in ((left, Qt.AlignLeft), (right, Qt.AlignRight)):
        label = QLabel(text)
        label.setStyleSheet("color: palette(mid); font-size: 10px;")
        row.addWidget(label, alignment=align)
    row.insertStretch(1, 1)
    return widget

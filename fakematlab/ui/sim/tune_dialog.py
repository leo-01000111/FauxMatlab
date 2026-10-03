"""
"Tune…" for a PID block on the canvas.

The Analyse workspace's PID Tuner asks you to type a plant in. Here the plant
is already drawn: the canvas opens the loop at the PID, linearises everything
else, and hands this dialog the transfer function the controller actually
sees. The dialog then does what the tuner does — two sliders, the same
:func:`~fakematlab.core.pidtune.tune` arithmetic — but small, modal, and ending
in gains written back to the block.

It never touches the model itself. ``changes`` holds the parameters to apply and
the canvas pushes them through the undo stack, so Cancel leaves no trace and
OK is one Ctrl+Z away from the old gains.
"""

from __future__ import annotations

import control as ctl
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
)

from ...core.pidtune import (
    PIDKind,
    TuneResult,
    crossover_for,
    phase_margin_for,
    reference_to_output,
    tune,
)
from ...core.timeresp import step_response
from ...core.tuning import PIDParams, pid_tf
from .. import theme
from ..apps.pid_tuner import SPEED_TICKS, TRANSIENT_TICKS, _ends, _settles
from ..plots import add_hline, curve_pen, make_plot


class PIDTuneDialog(QDialog):
    """
    Pick a controller type and two sliders; see the response; take the gains.

    ``plant`` is ``G·H`` as the controller sees it, or ``None`` with ``error``
    saying why it could not be found — then the controls are disabled and the
    message is the whole dialog.
    """

    def __init__(self, block, plant: ctl.TransferFunction | None,
                 error: str = "", notes: list[str] | tuple[str, ...] = (),
                 parent=None) -> None:
        super().__init__(parent)
        self.block = block
        self._plant = plant
        #: The latest tuning attempt (not `result`: QDialog owns that name).
        self.tuned: TuneResult | None = None
        #: Parameters to write to the block; empty until OK is accepted.
        self.changes: dict[str, float] = {}
        self.setWindowTitle(f"Tune {block.block_id}")
        self.resize(500, 400)

        root = QVBoxLayout(self)
        root.setSpacing(4)

        form = QFormLayout()
        self._kind = QComboBox()
        self._kind.addItems([k.value for k in PIDKind])
        self._kind.setCurrentText(self._initial_kind())
        self._kind.currentIndexChanged.connect(self.retune)
        form.addRow("Controller:", self._kind)

        self._tf = QDoubleSpinBox()
        self._tf.setRange(1e-4, 10.0)
        self._tf.setDecimals(4)
        self._tf.setSingleStep(0.005)
        self._tf.setValue(max(float(block.params.get("Tf", 0.01)), 1e-4))
        self._tf.setToolTip(
            "Derivative filter time constant. The block always filters its "
            "derivative, so this is never zero.")
        self._tf.valueChanged.connect(self.retune)
        form.addRow("Tf (D filter):", self._tf)
        root.addLayout(form)

        self._speed_label = QLabel()
        root.addWidget(self._speed_label)
        self._speed = QSlider(Qt.Horizontal)
        self._speed.setRange(-SPEED_TICKS, SPEED_TICKS)
        self._speed.setValue(0)
        self._speed.valueChanged.connect(self.retune)
        root.addWidget(self._speed)
        root.addWidget(_ends("slower", "faster"))

        self._transient_label = QLabel()
        root.addWidget(self._transient_label)
        self._transient = QSlider(Qt.Horizontal)
        self._transient.setRange(0, TRANSIENT_TICKS)
        self._transient.setValue(TRANSIENT_TICKS // 2)
        self._transient.valueChanged.connect(self.retune)
        root.addWidget(self._transient)
        root.addWidget(_ends("aggressive", "robust"))

        self._plot = make_plot("Closed-loop step response", "Time (s)", "y(t)")
        self._plot.setMinimumHeight(130)
        root.addWidget(self._plot, stretch=1)

        self._readout = QLabel()
        self._readout.setWordWrap(True)
        self._readout.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self._readout)

        self._notice = QLabel("\n".join(notes))
        self._notice.setWordWrap(True)
        self._notice.setStyleSheet("color: palette(mid);")
        self._notice.setVisible(bool(notes))
        root.addWidget(self._notice)

        self._error = QLabel(error)
        self._error.setWordWrap(True)
        self._error.setVisible(bool(error))
        root.addWidget(self._error)
        self._readout.setFont(theme.data_font(9))
        self._restyle()
        theme.notifier().changed.connect(self._restyle)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._buttons.button(QDialogButtonBox.Ok).setText("Apply gains")
        self._buttons.accepted.connect(self._accept)
        self._buttons.rejected.connect(self.reject)
        root.addWidget(self._buttons)

        if plant is None:
            for widget in (self._kind, self._tf, self._speed,
                           self._transient, self._plot):
                widget.setEnabled(False)
            self._plot.setVisible(False)
            self._speed_label.setVisible(False)
            self._transient_label.setVisible(False)
            self._buttons.button(QDialogButtonBox.Ok).setEnabled(False)
            if not error:
                self._error.setText("No plant to tune against.")
                self._error.setVisible(True)
        else:
            self.retune()

    # ── state ───────────────────────────────────────────────────

    def _initial_kind(self) -> str:
        """Start on the structure the block's current gains already are."""
        p = self.block.params
        if p.get("Kd", 0.0) and p.get("Ki", 0.0):
            return "PID"
        if p.get("Kd", 0.0):
            return "PD"
        return "PI" if p.get("Ki", 0.0) else "P"

    @property
    def kind(self) -> PIDKind:
        return PIDKind(self._kind.currentText())

    @property
    def speed(self) -> float:
        return self._speed.value() / SPEED_TICKS

    @property
    def transient(self) -> float:
        return self._transient.value() / TRANSIENT_TICKS

    def _current_controller(self) -> ctl.TransferFunction:
        p = self.block.params
        return pid_tf(PIDParams(Kp=float(p["Kp"]), Ki=float(p["Ki"]),
                                Kd=float(p["Kd"]), Tf=float(p["Tf"])))

    # ── tuning ──────────────────────────────────────────────────

    def retune(self, *_ignored) -> None:
        if self._plant is None:
            return
        try:
            pm = phase_margin_for(self.transient)
            wc = crossover_for(self._plant, self.speed, pm, self.kind)
            self._speed_label.setText(
                f"Response time — target ωc = {wc:.4g} rad/s "
                f"(≈ {2.0 / wc:.3g} s)")
            self._transient_label.setText(
                f"Transient behaviour — target phase margin = {pm:.1f}°")
            self.tuned = tune(self._plant, self.kind, wc=wc, pm_deg=pm,
                               Tf=float(self._tf.value()))
        except Exception as exc:                                # noqa: BLE001
            # A plant the loop-shaping arithmetic cannot digest (zero gain,
            # improper) is a message, not a crash inside a slider callback.
            self.tuned = None
            self._readout.setText(f"Cannot tune this plant: {exc}")
            self._buttons.button(QDialogButtonBox.Ok).setEnabled(False)
            return

        result = self.tuned
        ok = result.feasible and result.stable
        self._buttons.button(QDialogButtonBox.Ok).setEnabled(ok)
        self._readout.setText(result.describe() if result.feasible
                              else result.describe()
                              + "\nMove the response-time slider.")
        self._draw(result)

    def _draw(self, result: TuneResult) -> None:
        plot = self._plot.getPlotItem()
        plot.clear()
        plot.addLegend(offset=(-10, 10))
        curves: list[tuple[str, ctl.TransferFunction, int]] = []
        try:
            before = reference_to_output(self._current_controller(),
                                         self._plant)
            if _settles(before):
                curves.append(("current gains", before, 1))
        except Exception:                                       # noqa: BLE001
            pass
        if result.feasible and result.stable:
            curves.append((f"tuned {result.kind.value}", result.T, 0))
        for label, system, colour in curves:
            try:
                resp = step_response(system)
            except Exception:                                   # noqa: BLE001
                continue
            plot.plot(resp.t, np.atleast_2d(resp.y)[0],
                      pen=curve_pen(colour, 2.0), name=label)
        add_hline(plot, 1.0, theme.plot_colour("reference"), width=0.8)
        plot.setTitle("Closed-loop step response" if curves
                      else "Nothing stable to show at this target")

    def _restyle(self, *_args) -> None:
        self._error.setStyleSheet(f"color: {theme.tokens().hold_ink};")

    # ── accepting ───────────────────────────────────────────────

    def gains(self) -> dict[str, float] | None:
        """The block parameters the current tuning would write, or ``None``."""
        if self.tuned is None or not self.tuned.feasible \
                or not self.tuned.stable:
            return None
        params = self.tuned.params
        return {"Kp": float(params.Kp), "Ki": float(params.Ki),
                "Kd": float(params.Kd), "Tf": float(self._tf.value())}

    def _accept(self) -> None:
        gains = self.gains()
        if gains is None:
            return
        # Only what differs, so an unchanged Tf does not put a no-op entry in
        # the undo text and P/PI still zero the terms they do not use.
        self.changes = {k: v for k, v in gains.items()
                        if v != self.block.params.get(k)}
        self.accept()

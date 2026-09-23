"""
The Control System Designer — sisotool, the useful half.

Three linked plots: the root locus you drag a closed-loop pole on, the Bode
plot of the resulting open loop with its margins, and the step response of the
resulting closed loop. Move the pole and the other two follow.

**Why the locus does not move when the gain does.** The locus is computed for
the compensator with its gain set to 1, so the curve on screen is fixed and
the gain is a *position along it*. Recomputing the locus for each new gain
would redraw the same curve while the marker stayed put — the opposite of what
the gesture is supposed to show.
"""

from __future__ import annotations

import control as ctl
import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QCheckBox, QDoubleSpinBox, QFormLayout,
                               QGroupBox, QHBoxLayout, QLineEdit,
                               QPushButton, QSlider, QSplitter, QTextEdit,
                               QVBoxLayout, QWidget)

from ...core.designer import (Compensator, DesignSummary, damping_ray,
                              evaluate, gain_for_damping, gain_for_overshoot,
                              point_to_gain)
from ..guard import GuardedPanel, guard
from ..plots import (add_hline, add_marker, add_vline, curve_pen,
                     freq_vline, make_freq_plot, make_plot, plot_freq)

#: How long after the last drag event before the linked plots are recomputed.
#: Short enough to feel live, long enough that a fast drag does not queue up
#: one root-solve and one step simulation per mouse event.
DRAG_INTERVAL_MS = 60


class ControlSystemDesigner(QWidget, GuardedPanel):
    """Drag a closed-loop pole; watch the Bode plot and step response move."""

    #: The user pressed "Apply as K₂".
    compensator_applied = Signal(object)        # TransferFunction

    def __init__(self, plant: ctl.TransferFunction | None = None,
                 compensator: Compensator | None = None,
                 sensor: ctl.TransferFunction | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Control System Designer")
        self.resize(1180, 760)
        self._plant = plant if plant is not None else ctl.tf([1], [1, 3, 2, 0])
        self._sensor = sensor
        self.compensator = compensator or Compensator()
        self._summary: DesignSummary | None = None
        self._locus_note = ""
        self._target: pg.TargetItem | None = None
        self._pole_markers = None
        self._syncing = False

        self._drag_timer = QTimer(self)
        self._drag_timer.setSingleShot(True)
        self._drag_timer.setInterval(DRAG_INTERVAL_MS)
        self._drag_timer.timeout.connect(self._on_drag_settled)

        self._build_ui()
        self.rebuild()

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
        panel.setMaximumWidth(320)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)

        # ── gain ──
        gain_box = QGroupBox("Gain")
        gain_lay = QVBoxLayout(gain_box)
        self._gain_spin = QDoubleSpinBox()
        self._gain_spin.setDecimals(5)
        self._gain_spin.setRange(0.0, 1e7)
        self._gain_spin.setValue(self.compensator.gain)
        self._gain_spin.valueChanged.connect(self._on_gain_typed)
        gain_lay.addWidget(self._gain_spin)

        # A log slider: gains that matter span decades, and a linear slider
        # would spend nine tenths of its travel above the interesting range.
        self._gain_slider = QSlider(Qt.Horizontal)
        self._gain_slider.setRange(-300, 400)       # 10^-3 … 10^4
        self._gain_slider.setValue(0)
        self._gain_slider.valueChanged.connect(self._on_gain_slid)
        gain_lay.addWidget(self._gain_slider)
        lay.addWidget(gain_box)

        # ── compensator ──
        comp_box = QGroupBox("Compensator C(s)")
        comp_lay = QFormLayout(comp_box)
        self._zeros_edit = QLineEdit()
        self._zeros_edit.setPlaceholderText("-1, -2+3j")
        self._poles_edit = QLineEdit()
        self._poles_edit.setPlaceholderText("-10, 0")
        for edit in (self._zeros_edit, self._poles_edit):
            edit.editingFinished.connect(self.rebuild)
        comp_lay.addRow("Zeros:", self._zeros_edit)
        comp_lay.addRow("Poles:", self._poles_edit)

        quick = QHBoxLayout()
        for label, slot in (("+ integrator", self._add_integrator),
                            ("+ lead", self._add_lead)):
            button = QPushButton(label)
            button.clicked.connect(slot)
            quick.addWidget(button)
        comp_lay.addRow(quick)
        lay.addWidget(comp_box)

        # ── design targets ──
        target_box = QGroupBox("Pick the gain for a target")
        target_lay = QFormLayout(target_box)
        self._zeta_spin = QDoubleSpinBox()
        self._zeta_spin.setRange(0.01, 0.99)
        self._zeta_spin.setSingleStep(0.05)
        self._zeta_spin.setValue(0.5)
        zeta_btn = QPushButton("Set K for ζ")
        zeta_btn.clicked.connect(self._set_gain_for_damping)
        target_lay.addRow(self._zeta_spin, zeta_btn)

        self._mp_spin = QDoubleSpinBox()
        self._mp_spin.setRange(0.1, 99.0)
        self._mp_spin.setSuffix(" %")
        self._mp_spin.setValue(16.3)
        mp_btn = QPushButton("Set K for overshoot")
        mp_btn.clicked.connect(self._set_gain_for_overshoot)
        target_lay.addRow(self._mp_spin, mp_btn)
        lay.addWidget(target_box)

        self._rays_check = QCheckBox("Show constant-ζ rays")
        self._rays_check.setChecked(True)
        self._rays_check.toggled.connect(self.rebuild)
        lay.addWidget(self._rays_check)

        self._readout = QTextEdit()
        self._readout.setReadOnly(True)
        self._readout.setFont(QFont("Consolas", 9))
        lay.addWidget(self._readout, stretch=1)

        apply_btn = QPushButton("Apply as K₂")
        apply_btn.setToolTip(
            "Send this compensator to the architecture, so every tab "
            "analyses it.")
        apply_btn.clicked.connect(self._apply)
        lay.addWidget(apply_btn)
        return panel

    def _build_plots(self) -> QWidget:
        vertical = QSplitter(Qt.Vertical)

        horizontal = QSplitter(Qt.Horizontal)
        self._locus_widget = make_plot("Root locus", "Re", "Im")
        self._bode_widget = make_freq_plot("Open loop L(s)", "|L| (dB)")
        horizontal.addWidget(self._locus_widget)
        horizontal.addWidget(self._bode_widget)
        vertical.addWidget(horizontal)

        self._step_widget = make_plot("Closed-loop step response",
                                      "Time (s)", "y(t)")
        vertical.addWidget(self._step_widget)
        vertical.setStretchFactor(0, 3)
        vertical.setStretchFactor(1, 2)
        return vertical

    # ── plant and compensator ───────────────────────────────────

    def set_plant(self, plant: ctl.TransferFunction,
                  sensor: ctl.TransferFunction | None = None) -> None:
        self._plant = plant
        self._sensor = sensor
        self.rebuild()

    def set_compensator(self, compensator: Compensator) -> None:
        self.compensator = compensator
        self._zeros_edit.setText(_join(compensator.zeros))
        self._poles_edit.setText(_join(compensator.poles))
        self._gain_spin.setValue(compensator.gain)
        self.rebuild()

    def _add_integrator(self) -> None:
        self._poles_edit.setText(_append(self._poles_edit.text(), "0"))
        self.rebuild()

    def _add_lead(self) -> None:
        """A lead section an order of magnitude apart, as a starting point."""
        self._zeros_edit.setText(_append(self._zeros_edit.text(), "-1"))
        self._poles_edit.setText(_append(self._poles_edit.text(), "-10"))
        self.rebuild()

    # ── gain changes ────────────────────────────────────────────

    def _on_gain_typed(self, value: float) -> None:
        if self._syncing:
            return
        self.set_gain(float(value))

    def _on_gain_slid(self, ticks: int) -> None:
        if self._syncing:
            return
        self.set_gain(float(10.0 ** (ticks / 100.0)))

    def set_gain(self, gain: float) -> None:
        self.compensator.gain = max(float(gain), 0.0)
        self._sync_gain_widgets()
        self.update_gain()

    def _sync_gain_widgets(self) -> None:
        self._syncing = True
        self._gain_spin.setValue(self.compensator.gain)
        if self.compensator.gain > 0:
            self._gain_slider.setValue(
                int(round(100.0 * np.log10(self.compensator.gain))))
        self._syncing = False

    # ── dragging ────────────────────────────────────────────────

    def _on_target_moved(self) -> None:
        if self._syncing or self._target is None:
            return
        self._drag_timer.start()

    def _on_drag_settled(self) -> None:
        if self._target is None:
            return
        pos = self._target.pos()
        self.pick_point(complex(pos.x(), pos.y()), snap=False)

    def _on_target_released(self) -> None:
        self._drag_timer.stop()
        if self._target is None:
            return
        pos = self._target.pos()
        self.pick_point(complex(pos.x(), pos.y()), snap=True)

    @guard("pole placement")
    def pick_point(self, point: complex, snap: bool = True) -> None:
        """
        Set the gain so a closed-loop pole lands as near ``point`` as the
        locus allows. ``snap`` moves the marker onto the pole it actually got.
        """
        if self._summary is None:
            return
        result = point_to_gain(_unit_loop(self._plant, self.compensator,
                                          self._sensor),
                               point, locus=self._summary.locus)
        self.compensator.gain = result.K
        self._sync_gain_widgets()
        self.update_gain()
        if snap:
            self._move_target(result.pole)

    def _move_target(self, pole: complex) -> None:
        if self._target is None:
            return
        self._syncing = True
        self._target.setPos(pg.Point(float(pole.real), float(pole.imag)))
        self._syncing = False

    # ── design targets ──────────────────────────────────────────

    @guard("damping target")
    def _set_gain_for_damping(self) -> None:
        self._apply_target(gain_for_damping(
            _unit_loop(self._plant, self.compensator, self._sensor),
            float(self._zeta_spin.value())),
            f"ζ = {self._zeta_spin.value():.2f}")

    @guard("overshoot target")
    def _set_gain_for_overshoot(self) -> None:
        self._apply_target(gain_for_overshoot(
            _unit_loop(self._plant, self.compensator, self._sensor),
            float(self._mp_spin.value())),
            f"{self._mp_spin.value():.1f}% overshoot")

    def _apply_target(self, point, description: str) -> None:
        if point is None:
            self.report_error(
                "design target",
                ValueError(f"No gain on this locus gives {description}. "
                           f"The branches never reach that damping — add a "
                           f"lead section to bend them left."))
            return
        self.compensator.gain = point.K
        self._sync_gain_widgets()
        self.update_gain()
        self._move_target(point.pole)

    def _apply(self) -> None:
        self.compensator_applied.emit(self.compensator.tf())

    # ── drawing ─────────────────────────────────────────────────

    @guard("designer")
    def rebuild(self, *_ignored) -> None:
        """Full redraw — the compensator's poles or zeros changed."""
        self.compensator.zeros = _parse(self._zeros_edit.text())
        self.compensator.poles = _parse(self._poles_edit.text())
        if not self.compensator.is_real_coefficient():
            raise ValueError(
                "A complex root needs its conjugate too, or the compensator "
                "has complex coefficients and cannot be built from real "
                "components. Add the mirrored root.")
        self._target = None
        self._pole_markers = None
        summary = evaluate(self._plant, self.compensator, self._sensor)
        self._summary = summary
        self._draw_locus(summary)
        self._draw_linked(summary)

    @guard("designer")
    def update_gain(self, *_ignored) -> None:
        """Cheap redraw — only the gain changed, so the locus stays put."""
        locus = self._summary.locus if self._summary is not None else None
        summary = evaluate(self._plant, self.compensator, self._sensor,
                           locus=locus)
        self._summary = summary
        self._draw_linked(summary)

    def _draw_linked(self, summary: DesignSummary) -> None:
        self._draw_bode(summary)
        self._draw_step(summary)
        self._draw_closed_loop_poles(summary)
        lines = [summary.describe()]
        if self._locus_note:
            lines.append(self._locus_note)
        self._readout.setPlainText("\n".join(lines))

    def _draw_locus(self, summary: DesignSummary) -> None:
        plot = self._locus_widget.getPlotItem()
        plot.clear()
        locus = summary.locus

        for branch in range(locus.roots.shape[1]):
            roots = locus.roots[:, branch]
            ok = np.isfinite(roots)
            plot.plot(roots[ok].real, roots[ok].imag,
                      pen=curve_pen(branch, 1.6))

        L_unit = _unit_loop(self._plant, self.compensator, self._sensor)
        for root, symbol, colour in (
                (np.atleast_1d(ctl.poles(L_unit)), "x", "#F45B69"),
                (np.atleast_1d(ctl.zeros(L_unit)), "o", "#4C9BE8")):
            if len(root):
                plot.plot(root.real, root.imag, pen=None, symbol=symbol,
                          symbolSize=14, symbolPen=pg.mkPen(colour, width=2.4),
                          symbolBrush=None)

        add_vline(plot, 0.0, "#888888", width=0.8)
        add_hline(plot, 0.0, "#888888", width=0.8)
        _frame(plot, locus.roots)

        if self._rays_check.isChecked():
            self._draw_damping_rays(plot, locus.roots)

        # The marginal gain goes in the readout, not the title. A title long
        # enough to outgrow its panel lays the whole plot out wider than the
        # scene and pushes the curves off the edge — see `plots.set_title`.
        self._locus_note = (
            f"locus crosses the imaginary axis at K = {locus.K_marginal:.4g}, "
            f"ω = {locus.omega_marginal:.4g}"
            if np.isfinite(locus.K_marginal)
            else "the locus never crosses the imaginary axis for K > 0")

        self._install_target(plot, summary)

    def _draw_damping_rays(self, plot, roots: np.ndarray) -> None:
        finite = roots[np.isfinite(roots)]
        radius = float(np.max(np.abs(finite))) if len(finite) else 1.0
        for zeta in (0.2, 0.4, 0.6, 0.8):
            ray = damping_ray(zeta, radius * 1.2)
            for sign in (1, -1):
                plot.plot(ray.real, sign * ray.imag,
                          pen=pg.mkPen("#555577", width=0.9,
                                       style=Qt.DotLine))

    def _install_target(self, plot, summary: DesignSummary) -> None:
        """The draggable marker, placed on the dominant closed-loop pole."""
        poles = summary.closed_loop_poles
        if not len(poles):
            return
        dominant = max(poles, key=lambda p: p.real)
        self._target = pg.TargetItem(
            pos=(float(dominant.real), float(dominant.imag)),
            size=14, symbol="s", movable=True,
            pen=pg.mkPen("#F4A261", width=2.5),
            hoverPen=pg.mkPen("#FFD166", width=3.0),
            label="drag me",
        )
        self._target.sigPositionChanged.connect(self._on_target_moved)
        self._target.sigPositionChangeFinished.connect(self._on_target_released)
        plot.addItem(self._target)

    def _draw_closed_loop_poles(self, summary: DesignSummary) -> None:
        plot = self._locus_widget.getPlotItem()
        if self._pole_markers is not None:
            plot.removeItem(self._pole_markers)
            self._pole_markers = None
        poles = summary.closed_loop_poles
        if not len(poles):
            return
        self._pole_markers = pg.ScatterPlotItem(
            x=poles.real, y=poles.imag, symbol="s", size=11,
            pen=pg.mkPen("#F4A261", width=2.0),
            brush=pg.mkBrush("#F4A26180"))
        plot.addItem(self._pole_markers)

    def _draw_bode(self, summary: DesignSummary) -> None:
        from ...core.freqresp import bode as _bode

        plot = self._bode_widget.getPlotItem()
        plot.clear()
        bd = _bode(summary.L)
        plot_freq(plot, bd.omega, bd.mag_dB, pen=curve_pen(0, 2.0))
        add_hline(plot, 0.0, "#888888", width=0.8)
        if np.isfinite(bd.wc) and bd.wc > 0:
            freq_vline(plot, bd.wc, color="#F4A261",
                       label=f"PM {bd.pm_deg:.1f}°")
        if np.isfinite(bd.w180) and bd.w180 > 0 and np.isfinite(bd.gm_dB):
            freq_vline(plot, bd.w180, color="#F45B69",
                       label=f"GM {bd.gm_dB:.2f} dB")

    def _draw_step(self, summary: DesignSummary) -> None:
        from ...core.timeresp import step_response

        plot = self._step_widget.getPlotItem()
        plot.clear()
        if not summary.stable:
            plot.setTitle("Closed loop is unstable — no step response to show")
            return
        resp = step_response(summary.T)
        y = np.atleast_2d(resp.y)[0]
        plot.plot(resp.t, y, pen=curve_pen(0, 2.0))
        add_hline(plot, 0.0, "#888888", width=0.6)
        metrics = summary.metrics
        if metrics is not None and np.isfinite(metrics.y_inf):
            add_hline(plot, metrics.y_inf, "#56C271", width=0.8,
                      label=f"y∞ = {metrics.y_inf:.4g}")
            if np.isfinite(metrics.tp):
                add_marker(plot, metrics.tp, metrics.y_max, color="#F45B69")
        plot.setTitle("Closed-loop step response")


# ──────────────────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────────────────

def _unit_loop(plant, compensator: Compensator, sensor):
    """``C/K · G · H`` — the loop whose root locus the gain slides along."""
    unit = Compensator(1.0, list(compensator.zeros), list(compensator.poles))
    H = sensor if sensor is not None else ctl.TransferFunction([1], [1])
    return unit.tf() * plant * H


def _parse(text: str) -> list[complex]:
    """
    Parse a comma-separated root list.

    Parsing happens here, inside a guarded caller, rather than in the line
    edit's own slot — a typo then shows up in the error banner instead of
    escaping as an unhandled exception from a Qt signal.
    """
    roots: list[complex] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            roots.append(complex(part.replace(" ", "")))
        except ValueError as exc:
            raise ValueError(
                f"{part!r} is not a number. Write roots as -1, -2.5, or "
                f"-1+2j for a complex one.") from exc
    return roots


def _join(roots: list[complex]) -> str:
    return ", ".join(
        f"{r.real:g}" if abs(r.imag) < 1e-12 else f"{r.real:g}{r.imag:+g}j"
        for r in roots)


def _append(text: str, item: str) -> str:
    text = text.strip()
    return f"{text}, {item}" if text else item


def _frame(plot, roots: np.ndarray) -> None:
    """Frame the locus without letting round-off set the scale."""
    finite = roots[np.isfinite(roots)]
    if not len(finite):
        return
    x_lo, x_hi = float(np.min(finite.real)), float(np.max(finite.real))
    span = max(x_hi - x_lo, 1e-9)
    y_span = max(float(np.max(np.abs(finite.imag))), 0.25 * span)
    plot.setXRange(x_lo - 0.2 * span, x_hi + 0.2 * span, padding=0)
    plot.setYRange(-1.2 * y_span, 1.2 * y_span, padding=0)

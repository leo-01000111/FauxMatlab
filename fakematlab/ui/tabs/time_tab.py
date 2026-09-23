"""
Time tab — step / impulse / ramp responses with metrics and parameter sweep.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.architecture import CourseArchitecture
from ...core.timeresp import (
    compute_step_metrics,
    impulse_response,
    parameter_sweep,
    ramp_response,
    step_response,
)
from ..guard import GuardedPanel, guard
from ..plots import (
    add_band,
    add_hline,
    add_marker,
    add_text_annotation,
    add_vline,
    apply_theme,
    curve_pen,
    make_plot,
)


class TimeTab(QWidget, GuardedPanel):

    def __init__(self, arch: CourseArchitecture, parent=None) -> None:
        super().__init__(parent)
        self._arch = arch
        self._build_ui()
        self._defer_refresh()

    # ── UI ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.install_error_banner(outer)
        body = QWidget()
        root = QHBoxLayout(body)
        root.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(body, stretch=1)

        # ── Left control panel ──
        ctrl = QWidget()
        ctrl.setMaximumWidth(260)
        ctrl_lay = QVBoxLayout(ctrl)

        # Signal selector
        grp_sig = QGroupBox("Signal")
        sig_lay = QFormLayout(grp_sig)
        self._in_combo = QComboBox()
        self._in_combo.addItems(["r", "di", "do", "n"])
        self._out_combo = QComboBox()
        self._out_combo.addItems(["y", "u", "e"])
        sig_lay.addRow("Input:",  self._in_combo)
        sig_lay.addRow("Output:", self._out_combo)
        ctrl_lay.addWidget(grp_sig)

        # Response type
        grp_resp = QGroupBox("Response")
        resp_lay = QFormLayout(grp_resp)
        self._resp_combo = QComboBox()
        self._resp_combo.addItems(["Step", "Impulse", "Ramp"])
        self._amp_spin = QDoubleSpinBox()
        self._amp_spin.setRange(-1e6, 1e6)
        self._amp_spin.setValue(1.0)
        self._amp_spin.setSingleStep(0.1)
        resp_lay.addRow("Type:",      self._resp_combo)
        resp_lay.addRow("Amplitude:", self._amp_spin)
        ctrl_lay.addWidget(grp_resp)

        # Band overlay
        grp_band = QGroupBox("Settling band")
        band_lay = QFormLayout(grp_band)
        self._band_2  = QCheckBox("±2%")
        self._band_5  = QCheckBox("±5%")
        self._band_2.setChecked(True)
        self._band_5.setChecked(True)
        band_lay.addRow(self._band_2)
        band_lay.addRow(self._band_5)
        ctrl_lay.addWidget(grp_band)

        # Parameter sweep
        grp_sw = QGroupBox("Parameter sweep")
        sw_lay = QFormLayout(grp_sw)
        self._sweep_check = QCheckBox("Enable sweep")
        self._sweep_param = QComboBox()
        self._sweep_param.addItems([
            "K (loop gain × K₂)", "Kp (P gain)", "Ki (I gain)",
            "Kd (D gain)", "Plant gain × G",
        ])
        self._sweep_vals = QLineEdit("0.5, 1, 2, 5")
        self._sweep_vals.setPlaceholderText("comma-separated values")
        sw_lay.addRow(self._sweep_check)
        sw_lay.addRow("Param:", self._sweep_param)
        sw_lay.addRow("Values:", self._sweep_vals)
        ctrl_lay.addWidget(grp_sw)

        # Refresh button
        self._refresh_btn = QPushButton("Compute")
        self._refresh_btn.clicked.connect(lambda: self.refresh())
        ctrl_lay.addWidget(self._refresh_btn)
        ctrl_lay.addStretch()
        root.addWidget(ctrl)

        # ── Right plot + metrics ──
        right = QSplitter(Qt.Vertical)

        self._plot = make_plot("Time Response", "Time (s)", "Amplitude")
        self._plot.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        right.addWidget(self._plot)

        # Metrics table
        grp_m = QGroupBox("Step Metrics")
        m_lay = QVBoxLayout(grp_m)
        self._metrics_table = QTableWidget(0, 2)
        self._metrics_table.setHorizontalHeaderLabels(["Metric", "Value"])
        self._metrics_table.horizontalHeader().setStretchLastSection(True)
        self._metrics_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._metrics_table.setAlternatingRowColors(True)
        self._metrics_table.verticalHeader().setVisible(False)
        self._metrics_table.verticalHeader().setDefaultSectionSize(22)
        # Ten metrics are computed; v1 capped the table at a height that showed
        # two of them, so eight were only reachable by scrolling a widget that
        # did not look scrollable.
        self._metrics_table.setMinimumHeight(10 * 22 + 30)
        m_lay.addWidget(self._metrics_table)
        right.addWidget(grp_m)

        right.setStretchFactor(0, 3)
        right.setStretchFactor(1, 2)
        root.addWidget(right, stretch=1)

        # Connect auto-refresh
        for w in [self._in_combo, self._out_combo,
                  self._resp_combo, self._sweep_check,
                  self._sweep_param]:
            if hasattr(w, 'currentIndexChanged'):
                w.currentIndexChanged.connect(self._defer_refresh)
            elif hasattr(w, 'stateChanged'):
                w.stateChanged.connect(self._defer_refresh)

    # ── Refresh ───────────────────────────────────────────────

    def _defer_refresh(self) -> None:
        QTimer.singleShot(0, self.refresh)

    @guard("Time response")
    def refresh(self, arch: CourseArchitecture | None = None) -> None:
        if arch is not None:
            self._arch = arch

        inp = self._in_combo.currentText()
        out = self._out_combo.currentText()
        rtype = self._resp_combo.currentText().lower()
        amp   = self._amp_spin.value()

        pi = self._plot.getPlotItem()
        pi.clear()
        apply_theme(pi, f"{rtype.capitalize()} Response  {inp}→{out}",
                    "Time (s)", "Amplitude")
        self._metrics_table.setRowCount(0)

        if self._sweep_check.isChecked():
            self._draw_sweep(pi, inp, out, rtype, amp)
        else:
            self._draw_single(pi, inp, out, rtype, amp)

    @guard("Single response")
    def _draw_single(self, pi, inp: str, out: str,
                     rtype: str, amp: float) -> None:
        tf = self._arch.get_closed_loop_tf(inp, out)

        m = None
        if rtype == "step":
            resp = step_response(tf, amplitude=amp)
            m = compute_step_metrics(resp)
            self._draw_metrics(m)
            y_inf = m.y_inf
        elif rtype == "impulse":
            resp = impulse_response(tf, amplitude=amp)
            y_inf = None
        else:
            resp = ramp_response(tf, slope=amp)
            y_inf = None

        pi.plot(resp.t, resp.y.ravel(), pen=curve_pen(0, width=2.2),
                name=f"{inp}→{out}")

        if rtype == "step" and y_inf is not None and np.isfinite(y_inf):
            # Draw steady-state line
            add_hline(pi, y_inf, color="#888888", label=f"y∞={y_inf:.4g}")
            # ±2% and ±5% bands
            if self._band_2.isChecked() and not np.isnan(y_inf):
                add_band(pi, y_inf, abs(y_inf) * 0.02, "#44FF44", alpha=25)
            if self._band_5.isChecked() and not np.isnan(y_inf):
                add_band(pi, y_inf, abs(y_inf) * 0.05, "#FFAA00", alpha=18)

            # Markers for metrics
            if not np.isnan(m.tp) and not np.isnan(m.y_max):
                add_marker(pi, m.tp, m.y_max, symbol="t", color="#F45B69")
                add_text_annotation(pi, m.tp, m.y_max,
                                    f"  tp={m.tp:.3g}s\n  Mp={m.Mp_pct:.1f}%",
                                    color="#F45B69")
            if self._band_2.isChecked() and not np.isnan(m.ts_2pct):
                add_vline(pi, m.ts_2pct, color="#44CC44",
                          label=f"ts2%={m.ts_2pct:.3g}s")
            if self._band_5.isChecked() and not np.isnan(m.ts_5pct):
                add_vline(pi, m.ts_5pct, color="#FFAA00",
                          label=f"ts5%={m.ts_5pct:.3g}s")

    @guard("Parameter sweep")
    def _draw_sweep(self, pi, inp: str, out: str,
                    rtype: str, amp: float) -> None:
        text = self._sweep_vals.text()
        try:
            raw_vals = [float(v.strip()) for v in text.split(",") if v.strip()]
        except ValueError as exc:
            raise ValueError(
                f"Could not read the sweep values {text!r} — expected numbers "
                f"separated by commas, e.g. '0.5, 1, 2, 5'"
            ) from exc
        if not raw_vals:
            raise ValueError("Enter at least one sweep value, e.g. '0.5, 1, 2, 5'")

        param_idx = self._sweep_param.currentIndex()

        def make_tf(val: float):
            arch_copy = _shallow_copy_arch(self._arch)
            _apply_sweep_param(arch_copy, param_idx, val)
            return arch_copy.get_closed_loop_tf(inp, out)

        result = parameter_sweep(make_tf, raw_vals,
                                 param_name=self._sweep_param.currentText(),
                                 response_type=rtype, amplitude=amp)

        pi.addLegend(offset=(-10, 10))
        for i, resp in enumerate(result.responses):
            t = resp.t
            y = resp.y.ravel()
            pi.plot(t, y, pen=curve_pen(i, width=2.0), name=resp.label)

    def _draw_metrics(self, m) -> None:
        rows = [(k, v) for k, v in m.as_dict().items()]
        self._metrics_table.setRowCount(len(rows))
        for r, (k, v) in enumerate(rows):
            self._metrics_table.setItem(r, 0, _item(k))
            self._metrics_table.setItem(r, 1, _item(_fmt_v(v)))

    def set_active_signal(self, signal_id: str) -> None:
        if signal_id in ("r", "di", "do", "n"):
            self._in_combo.setCurrentText(signal_id)
        elif signal_id in ("y", "u", "e"):
            self._out_combo.setCurrentText(signal_id)
        self._defer_refresh()


# ── Helpers ───────────────────────────────────────────────────

def _item(text: str) -> QTableWidgetItem:
    it = QTableWidgetItem(text)
    it.setTextAlignment(Qt.AlignCenter)
    return it


def _fmt_v(v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "N/A"
    if isinstance(v, float) and np.isinf(v):
        return "∞"
    return f"{v:.5g}"


def _shallow_copy_arch(arch: CourseArchitecture) -> CourseArchitecture:
    """Quick copy with same block TFs."""
    from ...core.architecture import CourseArchitecture
    return CourseArchitecture(
        G  = arch.block_tf("G"),
        K2 = arch.block_tf("K2"),
        K1 = arch.block_tf("K1"),
        H  = arch.block_tf("H"),
    )


def _apply_sweep_param(arch: CourseArchitecture,
                       param_idx: int, val: float) -> None:
    """
    Apply one sweep value to a copy of the architecture.

    Index 0 — scaling the existing K₂ by a gain — is the generalisation of the
    old "multi-K graph" script: it keeps whatever controller structure the user
    designed and sweeps the loop gain through it, rather than replacing the
    controller with a bare proportional gain.
    """
    from ...core.tuning import PIDParams, pid_tf

    if param_idx == 0:        # K · K₂(s), preserving the controller structure
        arch.set_block("K2", val * arch.block_tf("K2"))
    elif param_idx == 1:      # Kp
        arch.set_block("K2", pid_tf(PIDParams(Kp=val)))
    elif param_idx == 2:      # Ki, with Kp held at 1
        arch.set_block("K2", pid_tf(PIDParams(Kp=1.0, Ki=val)))
    elif param_idx == 3:      # Kd, with Kp held at 1
        arch.set_block("K2", pid_tf(PIDParams(Kp=1.0, Kd=val)))
    elif param_idx == 4:      # scale the plant — a crude uncertainty sweep
        arch.set_block("G", val * arch.block_tf("G"))
    else:
        raise ValueError(f"unknown sweep parameter index {param_idx}")

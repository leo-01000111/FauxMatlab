"""
Design tab — controller structure picker, live sliders, Z-N tuning,
snapshot comparison.
"""

from __future__ import annotations

import control as ctl
import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ...core.architecture import CourseArchitecture
from ...core.freqresp import bode as _bode
from ...core.timeresp import step_response
from ...core.tuning import (
    LeadLagParams,
    PIDParams,
    lag_tf,
    lead_tf,
    pid_tf,
    zn_step,
    zn_ultimate,
)
from ..guard import GuardedPanel, guard
from ..plots import (
    add_hline,
    apply_theme,
    curve_pen,
    freq_vline,
    make_freq_plot,
    make_plot,
    plot_freq,
)


class DesignTab(QWidget, GuardedPanel):
    """Controller design and tuning panel."""

    controller_changed = Signal(object)   # emits new K2 TransferFunction

    def __init__(self, arch: CourseArchitecture, parent=None) -> None:
        super().__init__(parent)
        self._arch = arch
        self._snapshots: list[tuple[str, ctl.TransferFunction]] = []
        self._current_tf: ctl.TransferFunction | None = None
        self._build_ui()
        QTimer.singleShot(0, self._refresh_from_arch)

    # ── UI ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.install_error_banner(outer)
        body = QWidget()
        root = QHBoxLayout(body)
        root.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(body, stretch=1)

        # ── Left: controller params ──
        left = QWidget()
        left.setFixedWidth(280)
        left_lay = QVBoxLayout(left)

        grp_type = QGroupBox("Controller type")
        type_lay = QFormLayout(grp_type)
        self._type_combo = QComboBox()
        self._type_combo.addItems(
            ["P", "PI", "PD", "PID (ideal)",
             "PID (filtered D)", "Lead", "Lag", "Lead-Lag"])
        self._type_combo.currentIndexChanged.connect(self._on_type_change)
        type_lay.addRow("K₂(s):", self._type_combo)
        left_lay.addWidget(grp_type)

        # PID params group
        self._pid_grp = QGroupBox("PID parameters")
        pid_lay = QFormLayout(self._pid_grp)
        self._Kp  = self._spin(1.0,   0.0, 1e6, 0.1)
        self._Ki  = self._spin(0.0,   0.0, 1e6, 0.1)
        self._Kd  = self._spin(0.0,   0.0, 1e6, 0.01)
        self._Tf  = self._spin(0.0,   0.0, 100, 0.01)
        pid_lay.addRow("Kp:", self._Kp)
        pid_lay.addRow("Ki:", self._Ki)
        pid_lay.addRow("Kd:", self._Kd)
        pid_lay.addRow("Tf (D filter):", self._Tf)
        left_lay.addWidget(self._pid_grp)

        # Lead/Lag params group
        self._ll_grp = QGroupBox("Lead/Lag parameters")
        ll_lay = QFormLayout(self._ll_grp)
        self._ll_K     = self._spin(1.0, 0.0, 1e6, 0.1)
        self._ll_alpha = self._spin(0.1, 1e-4, 100, 0.05)
        self._ll_tau   = self._spin(1.0, 1e-6, 1e6, 0.1)
        ll_lay.addRow("K:",    self._ll_K)
        ll_lay.addRow("α:",    self._ll_alpha)
        ll_lay.addRow("τ:",    self._ll_tau)
        ll_lay.addRow(QLabel("Lead: α<1  Lag: α>1"))
        left_lay.addWidget(self._ll_grp)
        self._ll_grp.hide()

        # Apply button
        self._apply_btn = QPushButton("Apply to Architecture")
        self._apply_btn.clicked.connect(self._apply_controller)
        left_lay.addWidget(self._apply_btn)

        # Z-N group
        grp_zn = QGroupBox("Ziegler–Nichols Auto-tune")
        zn_lay = QVBoxLayout(grp_zn)
        self._zn_step_btn = QPushButton("Reaction-curve method (step)")
        self._zn_ult_btn  = QPushButton("Ultimate-gain method")
        self._zn_type     = QComboBox()
        self._zn_type.addItems(["P", "PI", "PID"])
        self._zn_step_btn.clicked.connect(self._zn_step)
        self._zn_ult_btn.clicked.connect(self._zn_ultimate)
        zn_lay.addWidget(QLabel("Set K₂ using:"))
        zn_lay.addWidget(self._zn_type)
        zn_lay.addWidget(self._zn_step_btn)
        zn_lay.addWidget(self._zn_ult_btn)
        left_lay.addWidget(grp_zn)

        # Snapshot
        grp_snap = QGroupBox("Snapshots")
        snap_lay = QVBoxLayout(grp_snap)
        self._snap_btn = QPushButton("📌 Snapshot current")
        self._snap_btn.clicked.connect(self._take_snapshot)
        snap_lay.addWidget(self._snap_btn)
        left_lay.addWidget(grp_snap)

        self._zn_result_label = QLabel("")
        self._zn_result_label.setWordWrap(True)
        self._zn_result_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        left_lay.addWidget(self._zn_result_label)
        left_lay.addStretch()
        root.addWidget(left)

        # ── Right: plots ──
        right = QSplitter(Qt.Vertical)

        self._step_plot = make_plot("Step Response Comparison",
                                    "Time (s)", "Amplitude")
        right.addWidget(self._step_plot)

        self._bode_plot = make_freq_plot("Bode — Loop TF", "|L| (dB)")
        right.addWidget(self._bode_plot)

        right.setStretchFactor(0, 1)
        right.setStretchFactor(1, 1)
        root.addWidget(right)

        # Wire up parameter changes
        for spin in [self._Kp, self._Ki, self._Kd, self._Tf,
                     self._ll_K, self._ll_alpha, self._ll_tau]:
            spin.valueChanged.connect(self._on_param_change)

    # ── Helpers ───────────────────────────────────────────────

    @staticmethod
    def _spin(val, lo, hi, step) -> QDoubleSpinBox:
        sp = QDoubleSpinBox()
        sp.setRange(lo, hi)
        sp.setSingleStep(step)
        sp.setDecimals(4)
        sp.setValue(val)
        return sp

    # ── Arch sync ────────────────────────────────────────────

    def _refresh_from_arch(self) -> None:
        """Load current K2 from architecture into the editor."""
        self._current_tf = self._arch.block_tf("K2")
        self._update_plots()

    # ── Type switching ────────────────────────────────────────

    #: Index of the "Lag" entry in the controller-type combo.
    _LAG_INDEX = 6

    def _on_type_change(self, idx: int) -> None:
        is_lead_lag = idx >= 5
        self._pid_grp.setVisible(not is_lead_lag)
        self._ll_grp.setVisible(is_lead_lag)
        # Show/hide Ki / Kd based on controller type
        self._Ki.setEnabled(idx in (1, 3, 4))
        self._Kd.setEnabled(idx in (2, 3, 4))
        self._Tf.setEnabled(idx == 4)

        if is_lead_lag:
            self._constrain_alpha_to_type(idx)
        self._on_param_change()

    def _constrain_alpha_to_type(self, idx: int) -> None:
        """
        Keep α on the correct side of 1 for the selected structure.

        A lead needs α < 1 and a lag α > 1, so a type change can leave the
        spinbox holding a value the builder rejects. Constraining the control
        means an invalid combination cannot be selected in the first place,
        rather than being reported after the fact.
        """
        wants_lag = (idx == self._LAG_INDEX)
        alpha = self._ll_alpha.value()

        self._ll_alpha.blockSignals(True)
        if wants_lag:
            self._ll_alpha.setRange(1.0001, 1000.0)
            if alpha <= 1.0:
                self._ll_alpha.setValue(max(1.0 / alpha, 1.0001)
                                        if alpha > 0 else 10.0)
            self._ll_alpha.setToolTip("Lag: α > 1 (pole below the zero)")
        else:
            self._ll_alpha.setRange(1e-4, 0.9999)
            if alpha >= 1.0:
                self._ll_alpha.setValue(min(1.0 / alpha, 0.9999))
            self._ll_alpha.setToolTip("Lead: α < 1 (pole above the zero)")
        self._ll_alpha.blockSignals(False)

    def _on_param_change(self, *_) -> None:
        """Live update: build TF from current params and refresh plots."""
        tf = self._build_tf()
        if tf is not None:
            self._current_tf = tf
            self._update_plots()

    @guard("Controller construction")
    def _build_tf(self) -> ctl.TransferFunction | None:
        idx = self._type_combo.currentIndex()
        try:
            if idx <= 4:  # PID family
                p = PIDParams(
                    Kp=self._Kp.value(),
                    Ki=self._Ki.value() if idx in (1, 3, 4) else 0.0,
                    Kd=self._Kd.value() if idx in (2, 3, 4) else 0.0,
                    Tf=self._Tf.value() if idx == 4 else 0.0,
                )
                return pid_tf(p)
            elif idx == 5:  # Lead
                p = LeadLagParams(K=self._ll_K.value(),
                                  alpha=self._ll_alpha.value(),
                                  tau=self._ll_tau.value(), is_lead=True)
                return lead_tf(p)
            elif idx == 6:  # Lag
                p = LeadLagParams(K=self._ll_K.value(),
                                  alpha=self._ll_alpha.value(),
                                  tau=self._ll_tau.value(), is_lead=False)
                return lag_tf(p)
            elif idx == 7:  # Lead-Lag: a lead section times a lag section
                alpha = self._ll_alpha.value()
                p_lead = LeadLagParams(K=self._ll_K.value(), alpha=alpha,
                                       tau=self._ll_tau.value(), is_lead=True)
                p_lag  = LeadLagParams(K=1.0, alpha=1.0 / alpha,
                                       tau=self._ll_tau.value() * 10,
                                       is_lead=False)
                return lead_tf(p_lead) * lag_tf(p_lag)
        except ValueError as exc:
            # Parameter combinations the builders reject (e.g. α ≥ 1 for a
            # lead) are user errors, not bugs — say so instead of blanking.
            self.report_error("Controller parameters", exc)
            return None

    # ── Apply ────────────────────────────────────────────────

    def _apply_controller(self) -> None:
        if self._current_tf is None:
            return
        self._arch.set_block("K2", self._current_tf)
        self.controller_changed.emit(self._current_tf)
        self._update_plots()

    # ── Ziegler–Nichols ───────────────────────────────────────

    def _zn_step(self) -> None:
        G = self._arch.block_tf("G")
        try:
            result = zn_step(G)
        except ValueError as exc:
            # The method does not apply to this plant. That is a real answer,
            # not a crash — show the reason, which says what to do instead.
            self._zn_result_label.setText(
                f"⚠ Reaction-curve method does not apply here:\n\n{exc}")
            return

        ctrl_type = self._zn_type.currentText()
        params = getattr(result, f"{ctrl_type}_params")
        self._load_pid_params(params)
        self._zn_result_label.setText(
            f"ZN step method:\n"
            f"L={result.L:.4g}s  T={result.T:.4g}s\n"
            f"DC gain={result.dc_gain:.4g}\n"
            f"→ Kp={params.Kp:.4g}  Ki={params.Ki:.4g}  Kd={params.Kd:.4g}"
        )
        self._on_param_change()

    def _zn_ultimate(self) -> None:
        G = self._arch.block_tf("G")
        try:
            result = zn_ultimate(G)
        except ValueError as exc:
            # The method does not apply to this plant. That is a real answer,
            # not a crash — show the reason, which says what to do instead.
            self._zn_result_label.setText(
                f"⚠ Ultimate-gain method does not apply here:\n\n{exc}")
            return

        ctrl_type = self._zn_type.currentText()
        params = getattr(result, f"{ctrl_type}_params")
        self._load_pid_params(params)
        self._zn_result_label.setText(
            f"ZN ultimate gain:\n"
            f"Ku={result.Ku:.4g}  Tu={result.Tu:.4g}s\n"
            f"→ Kp={params.Kp:.4g}  Ki={params.Ki:.4g}  Kd={params.Kd:.4g}"
        )
        self._on_param_change()

    def _load_pid_params(self, params: PIDParams) -> None:
        self._type_combo.setCurrentIndex(3)  # PID ideal
        self._Kp.setValue(params.Kp)
        self._Ki.setValue(params.Ki)
        self._Kd.setValue(params.Kd)

    # ── Snapshot ──────────────────────────────────────────────

    def _take_snapshot(self) -> None:
        if self._current_tf is None:
            return
        name = f"Snapshot {len(self._snapshots)+1}"
        self._snapshots.append((name, self._current_tf))
        self._update_plots()

    # ── Plots ────────────────────────────────────────────────

    def _update_plots(self) -> None:
        if self._current_tf is None:
            return
        self._draw_step()
        self._draw_bode()

    @guard("Design step response")
    def _draw_step(self) -> None:
        pi = self._step_plot.getPlotItem()
        pi.clear()
        apply_theme(pi, "Step Response (r→y)", "Time (s)", "Amplitude")

        curves = [("Current K₂", self._current_tf)]
        for name, tf in self._snapshots[-4:]:   # keep last 4 snapshots
            curves.append((name, tf))

        pi.addLegend(offset=(-10, 10))
        for i, (name, K2) in enumerate(curves):
            arch = _make_arch(self._arch, K2)
            resp = step_response(arch.get_closed_loop_tf("r", "y"))
            pi.plot(resp.t, resp.y.ravel(),
                    pen=curve_pen(i, 2.2 if i == 0 else 1.5), name=name)
        add_hline(pi, 1.0, "#888888", width=0.6)

    @guard("Design Bode plot")
    def _draw_bode(self) -> None:
        pi = self._bode_plot.getPlotItem()
        pi.clear()
        apply_theme(pi, "Bode — Loop L = K₂·G·H", "ω (rad/s)", "|L| (dB)")
        pi.addLegend(offset=(-10, 10))

        curves = [("Current", self._current_tf)]
        curves += list(self._snapshots[-3:])

        for i, (name, K2) in enumerate(curves):
            arch = _make_arch(self._arch, K2)
            bd = _bode(arch.loop_tf())
            plot_freq(pi, bd.omega, bd.mag_dB,
                      pen=curve_pen(i, 2.0),
                      name=f"{name}  (PM {bd.pm_deg:.0f}°)"
                           if np.isfinite(bd.pm_deg) else name)
            if i == 0 and np.isfinite(bd.wc):
                freq_vline(pi, bd.wc, color="#F4A261",
                           label=f"ωc={bd.wc:.3g}")

        add_hline(pi, 0.0, "#888888", width=0.6)

    def refresh(self, arch: CourseArchitecture | None = None) -> None:
        if arch is not None:
            self._arch = arch
        self._refresh_from_arch()


# ── Helpers ──────────────────────────────────────────────────

def _make_arch(src: CourseArchitecture,
               K2: ctl.TransferFunction) -> CourseArchitecture:
    return CourseArchitecture(
        G=src.block_tf("G"), K2=K2,
        K1=src.block_tf("K1"), H=src.block_tf("H"),
    )

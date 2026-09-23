"""
Frequency tab — Bode, Nyquist, Nichols with annotated margins (ch.4, ch.6).

All frequency data is handed to the plot layer as **raw ω in rad/s**; see the
module docstring of :mod:`fakematlab.ui.plots` for why that matters.
"""

from __future__ import annotations

import control as ctl
import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...core.architecture import CourseArchitecture
from ...core.freqresp import bode, nichols, nyquist
from ..guard import GuardedPanel, guard
from ..plots import (
    COLORS,
    add_hline,
    add_marker,
    add_text_annotation,
    add_vline,
    apply_theme,
    curve_pen,
    freq_marker,
    freq_text,
    freq_vline,
    make_freq_plot,
    make_plot,
    plot_freq,
)


class FrequencyTab(QWidget, GuardedPanel):

    def __init__(self, arch: CourseArchitecture, parent=None) -> None:
        super().__init__(parent)
        self._arch = arch
        self._build_ui()
        QTimer.singleShot(0, self.refresh)

    # ── UI ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.install_error_banner(outer)

        body = QWidget()
        root = QHBoxLayout(body)
        root.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(body, stretch=1)

        # ── Left controls ──
        ctrl = QWidget()
        ctrl.setMaximumWidth(250)
        ctrl_lay = QVBoxLayout(ctrl)

        grp_sig = QGroupBox("Signal")
        sig_lay = QFormLayout(grp_sig)
        self._sig_combo = QComboBox()
        self._sig_combo.addItems([
            "Loop L = K₂GH", "Sensitivity S",
            "Compl. Sensitivity T", "Plant G",
            "r→y", "r→u",
        ])
        self._sig_combo.currentIndexChanged.connect(self._defer_refresh)
        sig_lay.addRow("TF:", self._sig_combo)
        ctrl_lay.addWidget(grp_sig)

        grp_overlay = QGroupBox("Overlays (Bode)")
        ov_lay = QVBoxLayout(grp_overlay)
        self._ov_S  = QCheckBox("Sensitivity S")
        self._ov_T  = QCheckBox("Compl. sensitivity T")
        self._ov_L  = QCheckBox("Loop L")
        for cb in [self._ov_S, self._ov_T, self._ov_L]:
            cb.stateChanged.connect(self._defer_refresh)
            ov_lay.addWidget(cb)
        ctrl_lay.addWidget(grp_overlay)

        grp_nyq = QGroupBox("Chart options")
        nyq_lay = QVBoxLayout(grp_nyq)
        self._nyq_mcircles = QCheckBox("M-circles / M-contours")
        self._nyq_mcircles.setChecked(True)
        self._nyq_mcircles.stateChanged.connect(self._defer_refresh)
        nyq_lay.addWidget(self._nyq_mcircles)
        ctrl_lay.addWidget(grp_nyq)

        # Template (gabarit) specification — ch.6 25–26/26, ch.7 17/20.
        grp_tpl = QGroupBox("Templates (gabarits)")
        tpl_lay = QFormLayout(grp_tpl)
        self._tpl_show = QCheckBox("Show forbidden regions")
        self._tpl_show.stateChanged.connect(self._defer_refresh)
        tpl_lay.addRow(self._tpl_show)
        self._tpl_wd = QDoubleSpinBox()
        self._tpl_wd.setRange(1e-4, 1e6); self._tpl_wd.setDecimals(4)
        self._tpl_wd.setValue(0.3)
        self._tpl_sd = QDoubleSpinBox()
        self._tpl_sd.setRange(1e-6, 1.0); self._tpl_sd.setDecimals(4)
        self._tpl_sd.setValue(0.1)
        self._tpl_wn = QDoubleSpinBox()
        self._tpl_wn.setRange(1e-4, 1e6); self._tpl_wn.setDecimals(4)
        self._tpl_wn.setValue(30.0)
        self._tpl_tn = QDoubleSpinBox()
        self._tpl_tn.setRange(1e-6, 1.0); self._tpl_tn.setDecimals(4)
        self._tpl_tn.setValue(0.05)
        for w in (self._tpl_wd, self._tpl_sd, self._tpl_wn, self._tpl_tn):
            w.valueChanged.connect(self._defer_refresh)
        tpl_lay.addRow("ω_d (dist. BW):", self._tpl_wd)
        tpl_lay.addRow("max |S| below:",  self._tpl_sd)
        tpl_lay.addRow("ω_n (noise from):", self._tpl_wn)
        tpl_lay.addRow("max |T| above:", self._tpl_tn)
        ctrl_lay.addWidget(grp_tpl)

        self._refresh_btn = QPushButton("Compute")
        self._refresh_btn.clicked.connect(lambda: self.refresh())
        ctrl_lay.addWidget(self._refresh_btn)

        self._margins_label = QLabel("")
        self._margins_label.setWordWrap(True)
        self._margins_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        ctrl_lay.addWidget(self._margins_label)
        ctrl_lay.addStretch()

        root.addWidget(ctrl)

        # ── Right: sub-tabs for Bode / Nyquist / Nichols ──
        self._sub_tabs = QTabWidget()

        bode_w = QWidget()
        bode_lay = QVBoxLayout(bode_w)
        self._bode_mag   = make_freq_plot("Bode — Magnitude", "|G| (dB)")
        self._bode_phase = make_freq_plot("Bode — Phase",     "Phase (°)")
        self._bode_mag.setXLink(self._bode_phase)   # pan/zoom the pair together
        bode_lay.addWidget(self._bode_mag)
        bode_lay.addWidget(self._bode_phase)
        self._sub_tabs.addTab(bode_w, "Bode")

        nyq_w = QWidget()
        nyq_lay = QVBoxLayout(nyq_w)
        self._nyq_plot = make_plot("Nyquist Diagram", "Re L(jω)", "Im L(jω)")
        self._nyq_plot.getPlotItem().setAspectLocked(True)
        nyq_lay.addWidget(self._nyq_plot)
        self._sub_tabs.addTab(nyq_w, "Nyquist")

        nichols_w = QWidget()
        nichols_lay = QVBoxLayout(nichols_w)
        self._nichols_plot = make_plot("Nichols Chart",
                                       "Open-loop phase (°)", "|L| (dB)")
        nichols_lay.addWidget(self._nichols_plot)
        self._sub_tabs.addTab(nichols_w, "Nichols")

        self._sub_tabs.currentChanged.connect(self._defer_refresh)
        root.addWidget(self._sub_tabs, stretch=1)

    # ── Refresh ───────────────────────────────────────────────

    def _defer_refresh(self, *_) -> None:
        QTimer.singleShot(0, self.refresh)

    @guard("Frequency analysis")
    def refresh(self, arch: CourseArchitecture | None = None) -> None:
        if arch is not None:
            self._arch = arch

        tf = self._selected_tf()
        if tf is None:
            return

        tab = self._sub_tabs.currentIndex()
        if tab == 0:
            self._draw_bode(tf)
        elif tab == 1:
            self._draw_nyquist(tf)
        elif tab == 2:
            self._draw_nichols(tf)

    # ── Bode ─────────────────────────────────────────────────

    @guard("Bode plot")
    def _draw_bode(self, tf: ctl.TransferFunction) -> None:
        # Hand bode() the *exact* closed-loop and sensitivity functions from
        # the architecture rather than letting it assume unity feedback —
        # they differ whenever H ≠ 1.
        bd = bode(tf,
                  closed_loop_tf=self._arch.compl_sensitivity(),
                  sensitivity_tf=self._arch.sensitivity())

        overlays: list[tuple[str, ctl.TransferFunction]] = []
        if self._ov_L.isChecked():
            overlays.append(("L", self._arch.loop_tf()))
        if self._ov_S.isChecked():
            overlays.append(("S", self._arch.sensitivity()))
        if self._ov_T.isChecked():
            overlays.append(("T", self._arch.compl_sensitivity()))

        # ── Magnitude ──
        pi_mag = self._bode_mag.getPlotItem()
        pi_mag.clear()
        apply_theme(pi_mag, "Bode — Magnitude", "ω (rad/s)", "|G| (dB)")
        pi_mag.addLegend(offset=(-10, 10))
        plot_freq(pi_mag, bd.omega, bd.mag_dB, pen=curve_pen(0, 2.2),
                  name=self._sig_combo.currentText())
        for i, (name, otf) in enumerate(overlays):
            obd = bode(otf)
            plot_freq(pi_mag, obd.omega, obd.mag_dB,
                      pen=curve_pen(i + 1, 1.6), name=name)

        add_hline(pi_mag, 0.0, color="#888888", width=0.8)
        if self._tpl_show.isChecked():
            self._draw_templates(pi_mag, bd)

        if np.isfinite(bd.wc):
            freq_vline(pi_mag, bd.wc, color="#F4A261", label=f"ωc={bd.wc:.3g}")
        if np.isfinite(bd.w180) and np.isfinite(bd.gm_dB):
            freq_vline(pi_mag, bd.w180, color="#F45B69",
                       label=f"ω₁₈₀={bd.w180:.3g}")
            freq_text(pi_mag, bd.w180, float(np.min(bd.mag_dB)) + 5,
                      f"GM={bd.gm_dB:.2f} dB", "#F45B69")
        if np.isfinite(bd.wr) and np.isfinite(bd.Mr):
            mr_dB = 20 * np.log10(max(bd.Mr, 1e-10))
            freq_marker(pi_mag, bd.wr, mr_dB, symbol="star", color="#9B72CF")
            freq_text(pi_mag, bd.wr, mr_dB + 2, f"Mr={bd.Mr:.3g}", "#9B72CF")

        # ── Phase ──
        pi_ph = self._bode_phase.getPlotItem()
        pi_ph.clear()
        apply_theme(pi_ph, "Bode — Phase", "ω (rad/s)", "Phase (°)")
        plot_freq(pi_ph, bd.omega, bd.phase_deg, pen=curve_pen(0, 2.2))
        for i, (_name, otf) in enumerate(overlays):
            obd = bode(otf)
            plot_freq(pi_ph, obd.omega, obd.phase_deg, pen=curve_pen(i + 1, 1.6))

        add_hline(pi_ph, -180.0, color="#888888", width=0.8)
        if np.isfinite(bd.wc):
            freq_vline(pi_ph, bd.wc, color="#F4A261",
                       label=f"PM={bd.pm_deg:.1f}°")
            freq_marker(pi_ph, bd.wc,
                        float(np.interp(bd.wc, bd.omega, bd.phase_deg)),
                        symbol="d", color="#F4A261")

        self._margins_label.setText(self._margin_text(bd))

    @guard("Templates")
    def _draw_templates(self, pi, bd) -> None:
        """
        Draw the low- and high-frequency templates on the open-loop magnitude
        (ch.6, 25–26/26 and ch.7, 17/20).

        The specification is written on ``S`` and ``T`` but drawn on ``|L|``,
        because ``|L|`` is what you shape:

        * **Disturbance rejection** below ``ω_d``: ``|S| ≤ s_d`` needs
          ``|L| ≥ 1/s_d − 1``, so everything *below* that line is forbidden.
        * **Noise rejection / robustness** above ``ω_n``: ``|T| ≤ t_n`` needs
          ``|L| ≤ t_n/(1 − t_n)``, so everything *above* that line is
          forbidden.

        The gap between them is the design freedom left at crossover — and
        when the two templates overlap, the specification is infeasible, which
        the plot then shows directly.
        """
        from ..plots import to_freq_coord

        w_d, s_d = self._tpl_wd.value(), self._tpl_sd.value()
        w_n, t_n = self._tpl_wn.value(), self._tpl_tn.value()

        lo_dB = 20 * np.log10(max(1.0 / s_d - 1.0, 1e-12))
        hi_dB = 20 * np.log10(max(t_n / max(1.0 - t_n, 1e-12), 1e-12))

        y_lo = float(np.min(bd.mag_dB)) - 20.0
        y_hi = float(np.max(bd.mag_dB)) + 20.0
        x_lo = float(to_freq_coord(bd.omega.min()))
        x_hi = float(to_freq_coord(bd.omega.max()))

        # Low-frequency block: |L| must stay above lo_dB up to w_d.
        self._forbidden_box(pi, x_lo, float(to_freq_coord(w_d)),
                            y_lo, lo_dB, "#F45B69")
        freq_text(pi, bd.omega.min() * 1.2, lo_dB,
                  f"  |S| ≤ {s_d:g} below ω={w_d:g}\n  → |L| ≥ {lo_dB:.1f} dB",
                  "#F45B69")

        # High-frequency block: |L| must stay below hi_dB from w_n up.
        self._forbidden_box(pi, float(to_freq_coord(w_n)), x_hi,
                            hi_dB, y_hi, "#9B72CF")
        freq_text(pi, w_n * 1.05, hi_dB,
                  f"  |T| ≤ {t_n:g} above ω={w_n:g}\n  → |L| ≤ {hi_dB:.1f} dB",
                  "#9B72CF")

        # Feasibility: the two constraints must leave a corridor.
        if w_n <= w_d or hi_dB >= lo_dB:
            freq_text(pi, np.sqrt(max(w_d * w_n, 1e-12)), (lo_dB + hi_dB) / 2,
                      "  ⚠ templates overlap — specification infeasible",
                      "#F4A261")

    @staticmethod
    def _forbidden_box(pi, x0: float, x1: float, y0: float, y1: float,
                       color: str) -> None:
        """Hatch a rectangle of forbidden (ω, |L|) combinations."""
        if x1 <= x0 or y1 <= y0:
            return
        c = pg.mkColor(color)
        c.setAlpha(45)
        rect = pg.QtWidgets.QGraphicsRectItem(x0, y0, x1 - x0, y1 - y0)
        rect.setBrush(pg.mkBrush(c))
        rect.setPen(pg.mkPen(color, width=1.2, style=Qt.DashLine))
        rect.setZValue(-30)
        pi.addItem(rect)

    @staticmethod
    def _margin_text(bd) -> str:
        def f(v, unit="", fmt=".4g"):
            if v is None or not np.isfinite(v):
                return "—"
            return f"{v:{fmt}}{unit}"

        lines = [
            f"GM = {f(bd.gm_dB, ' dB', '.2f')}",
            f"PM = {f(bd.pm_deg, '°', '.2f')}",
            f"ωc = {f(bd.wc, ' rad/s')}",
            f"ω₁₈₀ = {f(bd.w180, ' rad/s')}",
            f"Delay margin = {f(bd.dm_s, ' s')}",
            f"BW (−3 dB, T) = {f(bd.bw_3dB, ' rad/s')}",
            f"Mr = {f(bd.Mr)}  at {f(bd.wr, ' rad/s')}",
            f"Ms = {f(bd.Ms)}  → modulus margin {f(1.0 / bd.Ms if bd.Ms else None)}",
        ]
        if bd.stability_known:
            lines.append("Closed loop: " + ("stable" if bd.stable else "UNSTABLE"))
        else:
            lines.append("Closed loop: see note")
        if bd.note:
            lines.append("")
            lines.append("⚠ " + bd.note)
        return "\n".join(lines)

    # ── Nyquist ───────────────────────────────────────────────

    @guard("Nyquist plot")
    def _draw_nyquist(self, tf: ctl.TransferFunction) -> None:
        nd = nyquist(tf)

        pi = self._nyq_plot.getPlotItem()
        pi.clear()
        apply_theme(pi, "Nyquist Diagram", "Re L(jω)", "Im L(jω)")
        pi.addLegend(offset=(-10, 10))

        # M-circles go down first so the locus draws on top of them.
        if self._nyq_mcircles.isChecked():
            for i, (M, path) in enumerate(nd.m_circles):
                pi.plot(path.real, path.imag,
                        pen=pg.mkPen(COLORS[(i + 2) % len(COLORS)],
                                     width=0.8, style=Qt.DotLine),
                        name=f"|T|={M:g}")

        pi.plot(nd.H_pos.real, nd.H_pos.imag, pen=curve_pen(0, 2.0),
                name="L(jω), ω>0")
        pi.plot(nd.H_neg.real, nd.H_neg.imag,
                pen=pg.mkPen(COLORS[0], width=1.2, style=Qt.DashLine),
                name="L(−jω)")

        add_marker(pi, -1.0, 0.0, symbol="x", color="#FF4444", size=14)
        add_text_annotation(pi, -1.0, 0.05, "−1", "#FF4444")

        theta = np.linspace(0, 2 * np.pi, 200)
        pi.plot(np.cos(theta), np.sin(theta),
                pen=pg.mkPen("#666666", width=0.8, style=Qt.DotLine))

        # The modulus margin, drawn as the shortest chord to −1 (ch.6, 23/26).
        if np.isfinite(nd.w_modulus):
            i = int(np.argmin(np.abs(nd.omega - nd.w_modulus)))
            pi.plot([-1.0, nd.H_pos[i].real], [0.0, nd.H_pos[i].imag],
                    pen=pg.mkPen("#26BFBF", width=1.6, style=Qt.DashLine),
                    name=f"modulus margin = {nd.modulus_margin:.3g}")

        add_vline(pi, 0.0, "#555555", width=0.6)
        add_hline(pi, 0.0, "#555555", width=0.6)

        verdict = ("closed loop STABLE" if nd.Z == 0
                   else f"closed loop UNSTABLE — {nd.Z} RHP pole(s)")
        self._margins_label.setText(
            f"Nyquist criterion (ch.6, 10/26)\n"
            f"  N (CW encirclements of −1) = {nd.encirclements}\n"
            f"  P (open-loop RHP poles)    = {nd.P}\n"
            f"  Z = N + P                  = {nd.Z}\n"
            f"→ {verdict}\n\n"
            f"Modulus margin = {nd.modulus_margin:.4g} at ω = {nd.w_modulus:.4g}\n"
            f"GM = {nd.gm_dB:.2f} dB\n"
            f"PM = {nd.pm_deg:.2f}°"
        )

    # ── Nichols ───────────────────────────────────────────────

    @guard("Nichols chart")
    def _draw_nichols(self, tf: ctl.TransferFunction) -> None:
        nc = nichols(tf)

        pi = self._nichols_plot.getPlotItem()
        pi.clear()
        apply_theme(pi, "Nichols Chart", "Open-loop phase (°)", "|L| (dB)")
        pi.addLegend(offset=(-10, 10))

        if self._nyq_mcircles.isChecked():
            for i, (M, pts) in enumerate(nc.m_circles):
                if len(pts) == 0:
                    continue
                # connect='finite' respects the NaN rows that separate the
                # disjoint branches of an M-contour.
                pi.plot(pts[:, 0], pts[:, 1], connect="finite",
                        pen=pg.mkPen(COLORS[(i + 2) % len(COLORS)],
                                     width=0.8, style=Qt.DotLine),
                        name=f"|T|={M:g}")

        pi.plot(nc.phase_deg, nc.mag_dB, pen=curve_pen(0, 2.2),
                name=self._sig_combo.currentText())

        add_vline(pi, -180.0, "#FF4444", width=0.8)
        add_hline(pi, 0.0,    "#888888", width=0.8)
        add_marker(pi, -180.0, 0.0, symbol="x", color="#FF4444", size=12)

    # ── Helpers ───────────────────────────────────────────────

    def _selected_tf(self) -> ctl.TransferFunction | None:
        idx = self._sig_combo.currentIndex()
        getters = [
            self._arch.loop_tf,
            self._arch.sensitivity,
            self._arch.compl_sensitivity,
            self._arch.open_loop_tf,
            lambda: self._arch.get_closed_loop_tf("r", "y"),
            lambda: self._arch.get_closed_loop_tf("r", "u"),
        ]
        if 0 <= idx < len(getters):
            return getters[idx]()
        return None

    def set_active_signal(self, signal_id: str) -> None:
        mapping = {"r": 4, "u": 5, "e": 0, "y": 4, "di": 0, "do": 0, "n": 0}
        if signal_id in mapping:
            self._sig_combo.setCurrentIndex(mapping[signal_id])

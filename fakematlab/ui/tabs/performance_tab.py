"""
Performance tab — system type, error constants, trade-offs.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...core.architecture import CourseArchitecture
from ...core.freqresp import bode
from ...core.performance import analyse_performance, waterbed
from ..guard import GuardedPanel, guard
from ..plots import (
    add_hline,
    apply_theme,
    curve_pen,
    freq_marker,
    freq_text,
    freq_vline,
    make_freq_plot,
    plot_freq,
)


class PerformanceTab(QWidget, GuardedPanel):

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

        # ── Left: metrics ──
        left = QWidget()
        left.setMaximumWidth(320)
        left_lay = QVBoxLayout(left)

        grp_ess = QGroupBox("Steady-State Errors (unity feedback, unit input)")
        ess_lay = QVBoxLayout(grp_ess)
        self._ess_table = _make_table(["Metric", "Value"])
        self._ess_table.setMaximumHeight(300)
        ess_lay.addWidget(self._ess_table)
        left_lay.addWidget(grp_ess)

        self._refresh_btn = QPushButton("Compute")
        self._refresh_btn.clicked.connect(lambda: self.refresh())
        left_lay.addWidget(self._refresh_btn)

        self._summary_text = QTextEdit()
        self._summary_text.setReadOnly(True)
        self._summary_text.setMaximumHeight(200)
        left_lay.addWidget(self._summary_text)
        left_lay.addStretch()
        root.addWidget(left)

        # ── Right: plots ──
        right = QSplitter(Qt.Vertical)

        self._bode_plot = make_freq_plot("Sensitivity & Complementary Sensitivity",
                                         "Magnitude (dB)")
        right.addWidget(self._bode_plot)

        self._tradeoff_plot = make_freq_plot("Trade-off: S(jω) + T(jω) = 1",
                                             "Magnitude")
        self._tradeoff_plot.setXLink(self._bode_plot)
        right.addWidget(self._tradeoff_plot)

        right.setStretchFactor(0, 1)
        right.setStretchFactor(1, 1)
        root.addWidget(right)

    # ── Refresh ───────────────────────────────────────────────

    @guard("Performance analysis")
    def refresh(self, arch: CourseArchitecture | None = None) -> None:
        if arch is not None:
            self._arch = arch

        L  = self._arch.loop_tf()
        S  = self._arch.sensitivity()
        T  = self._arch.compl_sensitivity()

        bd_L = bode(L, closed_loop_tf=T, sensitivity_tf=S)
        rpt = analyse_performance(L, closed_loop_tf=T, bw_3dB=bd_L.bw_3dB)

        # Table
        rows = [
            ("System type",        str(rpt.system_type)),
            ("Kp (position const.)", _fmt(rpt.Kp)),
            ("Kv (velocity const.)", _fmt(rpt.Kv)),
            ("Ka (accel. const.)",   _fmt(rpt.Ka)),
            ("e_ss (step)",          _fmt(rpt.ess_step)),
            ("e_ss (ramp)",          _fmt(rpt.ess_ramp)),
            ("e_ss (parabola)",      _fmt(rpt.ess_parabola)),
            ("|S(0)| (DC distrej.)", _fmt(rpt.S_dc)),
            ("|T(0)| (DC tracking)", _fmt(rpt.T_dc)),
            ("BW −3dB (T)",          _fmt(rpt.bw_3dB) + " rad/s"),
        ]
        self._ess_table.setRowCount(len(rows))
        for r, (k, v) in enumerate(rows):
            self._ess_table.setItem(r, 0, _item(k))
            self._ess_table.setItem(r, 1, _item(v))

        wb = waterbed(L, sensitivity_tf=S)
        self._summary_text.setPlainText(
            rpt.summary
            + "\n\n── Bode–Freudenberg (ch.7, 18/20) ──\n"
            + wb.summary())

        # Plots
        self._draw_bode_S_T(S, T, bd_L)
        self._draw_tradeoff(S, T, wb)

    @guard("S / T magnitude plot")
    def _draw_bode_S_T(self, S, T, bd_L) -> None:
        pi = self._bode_plot.getPlotItem()
        pi.clear()
        apply_theme(pi, "Sensitivity S and Complementary Sensitivity T",
                    "ω (rad/s)", "Magnitude (dB)")
        pi.addLegend(offset=(-10, 10))

        # Share one frequency grid so the two curves are directly comparable.
        omega = bd_L.omega
        bd_S = bode(S, omega=omega)
        bd_T = bode(T, omega=omega)

        plot_freq(pi, omega, bd_S.mag_dB, pen=curve_pen(0, 2.0), name="|S|")
        plot_freq(pi, omega, bd_T.mag_dB, pen=curve_pen(1, 2.0), name="|T|")
        add_hline(pi, 0.0, "#888888", width=0.8)
        add_hline(pi, -3.0, "#FFAA00", label="−3 dB", width=0.8)

        # Peak sensitivity Ms: its reciprocal is the modulus margin, so this
        # marker is the single most informative point on the plot (ch.6 23/26).
        peak_idx = int(np.argmax(bd_S.mag_dB))
        Ms_dB = float(bd_S.mag_dB[peak_idx])
        if Ms_dB > 0:
            w_peak = float(omega[peak_idx])
            freq_marker(pi, w_peak, Ms_dB, symbol="t", color="#F45B69")
            freq_text(pi, w_peak, Ms_dB,
                      f"  Ms = {10 ** (Ms_dB / 20):.3g} ({Ms_dB:.2f} dB)\n"
                      f"  → modulus margin {10 ** (-Ms_dB / 20):.3g}",
                      "#F45B69")

        if np.isfinite(bd_L.bw_3dB):
            freq_vline(pi, bd_L.bw_3dB, color="#56C271",
                       label=f"BW={bd_L.bw_3dB:.3g}")

    @guard("Trade-off plot")
    def _draw_tradeoff(self, S, T, wb=None) -> None:
        pi = self._tradeoff_plot.getPlotItem()
        pi.clear()
        apply_theme(pi, "S(jω) + T(jω) = 1 — the trade-off you cannot escape",
                    "ω (rad/s)", "Magnitude")
        pi.addLegend(offset=(-10, 10))

        bd_S = bode(S)
        omega = bd_S.omega
        bd_T = bode(T, omega=omega)
        mag_S = 10 ** (bd_S.mag_dB / 20.0)
        mag_T = 10 ** (bd_T.mag_dB / 20.0)

        plot_freq(pi, omega, mag_S, pen=curve_pen(0, 2.0), name="|S|")
        plot_freq(pi, omega, mag_T, pen=curve_pen(1, 2.0), name="|T|")

        # S + T = 1 holds for the *complex* functions, so |S| + |T| ≥ 1 with
        # equality only where their phases align. v1 labelled a line at 1 as
        # "|S|+|T|=1", which is not true and hides the actual constraint —
        # plotting the sum makes the inequality visible.
        plot_freq(pi, omega, mag_S + mag_T,
                  pen=curve_pen(3, 1.4), name="|S| + |T|  (≥ 1)")
        add_hline(pi, 1.0, "#888888", label="1", width=0.8)

        # Where |S| > 1 the loop *amplifies* disturbance — Bode's waterbed.
        # Shading it makes the trade-off a picture rather than a claim: the
        # shaded area and the area below 1 must balance when the budget is 0.
        amplifying = mag_S > 1.0
        if amplifying.any():
            self._shade_amplified_band(pi, omega, amplifying)
            first = float(omega[np.argmax(amplifying)])
            label = "  |S| > 1: disturbance amplified here"
            if wb is not None and wb.applies:
                label += (f"\n  ∫ln|S|dω = {wb.integral:.3g}"
                          f"  (budget {wb.theoretical:.3g})")
            freq_text(pi, first, 1.05, label, "#F45B69")

    @staticmethod
    def _shade_amplified_band(pi, omega, amplifying) -> None:
        """Shade each contiguous frequency band where |S| exceeds 1."""
        from ..plots import freq_region
        edges = np.diff(amplifying.astype(int))
        starts = list(np.where(edges == 1)[0] + 1)
        ends = list(np.where(edges == -1)[0] + 1)
        if amplifying[0]:
            starts.insert(0, 0)
        if amplifying[-1]:
            ends.append(len(omega) - 1)
        for a, b in zip(starts, ends):
            freq_region(pi, float(omega[a]), float(omega[b]),
                        color="#F45B69", alpha=28)


# ── Helpers ───────────────────────────────────────────────────

def _make_table(headers: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QTableWidget.NoEditTriggers)
    t.horizontalHeader().setStretchLastSection(True)
    t.setAlternatingRowColors(True)
    return t


def _item(text: str) -> QTableWidgetItem:
    it = QTableWidgetItem(text)
    it.setTextAlignment(Qt.AlignCenter)
    return it


def _fmt(v: float) -> str:
    if np.isnan(v):   return "N/A"
    if np.isinf(v):   return "∞"
    return f"{v:.5g}"

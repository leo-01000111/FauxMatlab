"""
Stability tab — Routh table, root locus, closed-loop pole map.
"""

from __future__ import annotations

import numpy as np
import control as ctl
import sympy as sp
import pyqtgraph as pg
from PySide6.QtCore    import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QComboBox,
    QPushButton, QGroupBox, QFormLayout, QSplitter,
    QTableWidget, QTableWidgetItem, QCheckBox,
    QLineEdit, QDoubleSpinBox, QSizePolicy, QTabWidget,
)

from ..guard import GuardedPanel, guard
from ..plots import (make_plot, add_vline, add_hline, add_marker,
                      add_text_annotation, curve_pen, apply_theme,
                      draw_pz_map, COLORS)
from ...core.architecture import CourseArchitecture
from ...core.stability    import routh_from_closed_loop, root_locus
from ...core.tf_utils     import analyse
import pyqtgraph as pg


class StabilityTab(QWidget, GuardedPanel):

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
        ctrl.setMaximumWidth(260)
        ctrl_lay = QVBoxLayout(ctrl)

        grp_routh = QGroupBox("Routh–Hurwitz")
        routh_lay = QFormLayout(grp_routh)
        self._sym_K = QCheckBox("Symbolic K")
        routh_lay.addRow(self._sym_K)
        routh_lay.addRow(QLabel("(leaves K free in table)"))
        ctrl_lay.addWidget(grp_routh)

        grp_rl = QGroupBox("Root Locus")
        rl_lay = QFormLayout(grp_rl)
        self._rl_kmax = QDoubleSpinBox()
        self._rl_kmax.setRange(0.01, 1e6)
        self._rl_kmax.setValue(20.0)
        self._rl_kmax.setSingleStep(5.0)
        rl_lay.addRow("K_max:", self._rl_kmax)
        ctrl_lay.addWidget(grp_rl)

        self._refresh_btn = QPushButton("Compute")
        self._refresh_btn.clicked.connect(lambda: self.refresh())
        ctrl_lay.addWidget(self._refresh_btn)

        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        ctrl_lay.addWidget(self._status_label)
        ctrl_lay.addStretch()

        root.addWidget(ctrl)

        # ── Right: sub-tabs ──
        self._sub = QTabWidget()

        # Routh table tab
        routh_w = QWidget()
        routh_l = QVBoxLayout(routh_w)
        self._routh_info  = QLabel("")
        self._routh_info.setWordWrap(True)
        routh_l.addWidget(self._routh_info)
        self._routh_table = QTableWidget(0, 0)
        self._routh_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._routh_table.setAlternatingRowColors(True)
        routh_l.addWidget(self._routh_table)
        self._sub.addTab(routh_w, "Routh Table")

        # Root locus tab
        rl_w = QWidget()
        rl_l = QVBoxLayout(rl_w)
        self._rl_plot = make_plot("Root Locus", "Re(s)", "Im(s)")
        rl_l.addWidget(self._rl_plot)
        self._sub.addTab(rl_w, "Root Locus")

        # CL pole map tab
        pz_w = QWidget()
        pz_l = QVBoxLayout(pz_w)
        self._pz_plot = make_plot("Closed-Loop Poles", "Re(s)", "Im(s)")
        pz_l.addWidget(self._pz_plot)
        self._sub.addTab(pz_w, "CL Pole Map")

        self._sub.currentChanged.connect(self._defer_refresh)
        root.addWidget(self._sub)

    # ── Refresh ───────────────────────────────────────────────

    def _defer_refresh(self, *_) -> None:
        QTimer.singleShot(0, self.refresh)

    @guard("Analysis")
    def refresh(self, arch: CourseArchitecture | None = None) -> None:
        if arch is not None:
            self._arch = arch
        tab = self._sub.currentIndex()
        if tab == 0:
            self._draw_routh()
        elif tab == 1:
            self._draw_root_locus()
        elif tab == 2:
            self._draw_pz_map()

    # ── Routh ────────────────────────────────────────────────

    @guard("Routh table")
    def _draw_routh(self) -> None:
        G  = self._arch.block_tf("G")
        K2 = self._arch.block_tf("K2")
        sym_K = sp.Symbol('K') if self._sym_K.isChecked() else None

        result = routh_from_closed_loop(G, K2, K_sym=sym_K)

        # Info
        if result.is_symbolic:
            info = (f"Symbolic table with K free.\n"
                    f"Stability range: {result.K_stable_range}")
        else:
            s_str = "Stable" if result.stable else f"Unstable ({result.n_rhp_poles} RHP poles)"
            info  = f"Verdict: {s_str}"
        self._routh_info.setText(info)

        # Table
        arr   = result.table
        n_rows = len(arr)
        n_cols = max(len(row) for row in arr)
        self._routh_table.setRowCount(n_rows)
        self._routh_table.setColumnCount(n_cols + 1)
        headers = [f"s^{n_rows - 1 - r}" for r in range(n_rows)]
        self._routh_table.setVerticalHeaderLabels(headers)
        self._routh_table.setHorizontalHeaderLabels(
            [f"col {c}" for c in range(n_cols + 1)])

        for r, row in enumerate(arr):
            for c, val in enumerate(row):
                item = QTableWidgetItem(_routh_cell_text(result, val))
                item.setTextAlignment(Qt.AlignCenter)
                # A sign change down the first column is one RHP root, so
                # colour the negatives — that column is the whole criterion.
                if c == 0 and not result.is_symbolic:
                    fv = _as_float(val)
                    if fv is not None and fv < 0:
                        item.setForeground(pg.mkBrush("#FF5555"))
                self._routh_table.setItem(r, c, item)

        self._routh_table.resizeColumnsToContents()

    # ── Root locus ────────────────────────────────────────────

    @guard("Root locus")
    def _draw_root_locus(self) -> None:
        G  = self._arch.block_tf("G")
        K2 = self._arch.block_tf("K2")
        K_max = self._rl_kmax.value()

        pi = self._rl_plot.getPlotItem()
        pi.clear()
        apply_theme(pi, "Root Locus", "Re(s)", "Im(s)")

        rl = root_locus(G, K2=K2, K_min=0.0, K_max=K_max)

        # Draw each branch (one curve per open-loop pole)
        n_branches = rl.roots.shape[1]
        for j in range(n_branches):
            branch = rl.roots[:, j]
            pi.plot(branch.real, branch.imag,
                    pen=curve_pen(j, 1.8),
                    name=f"Branch {j+1}")

        # Mark open-loop poles (K=0) and zeros
        ol_poles = ctl.poles(K2 * G)
        ol_zeros = ctl.zeros(K2 * G)
        draw_pz_map(pi, list(ol_poles), list(ol_zeros))

        # Mark marginal gain crossing
        if not np.isnan(rl.K_marginal):
            add_vline(pi, 0.0, "#FFAA00", width=1.5)
            self._status_label.setText(
                f"Marginal gain Ku ≈ {rl.K_marginal:.4g}\n"
                f"Marginal frequency ≈ {rl.omega_marginal:.4g} rad/s"
            )
        else:
            self._status_label.setText("No imaginary-axis crossing found\n"
                                        "(system stable for all K > 0)")

        # Asymptotes
        if rl.asymptote_angles:
            for angle in rl.asymptote_angles:
                # Draw a line from the centroid in the asymptote direction
                c = rl.asymptote_centroid
                dx = np.cos(np.radians(angle)) * K_max
                dy = np.sin(np.radians(angle)) * K_max
                pi.plot([c, c + dx], [0, dy],
                        pen=pg.mkPen("#555555", width=0.8, style=Qt.DashLine))

        add_vline(pi, 0.0, "#888888", width=0.6)
        add_hline(pi, 0.0, "#888888", width=0.6)
        pi.addLegend()

    # ── CL pole map ────────────────────────────────────────────

    @guard("Closed-loop pole map")
    def _draw_pz_map(self) -> None:
        pi = self._pz_plot.getPlotItem()
        pi.clear()
        apply_theme(pi, "Closed-Loop Poles & Zeros", "Re(s)", "Im(s)")

        for i, (label, inp, out) in enumerate([
            ("r→y", "r", "y"), ("r→u", "r", "u"), ("r→e", "r", "e"),
        ]):
            tf   = self._arch.get_closed_loop_tf(inp, out)
            info = analyse(tf)
            if True:
                p_re = [p.value.real for p in info.poles]
                p_im = [p.value.imag for p in info.poles]
                z_re = [z.real for z in info.zeros]
                z_im = [z.imag for z in info.zeros]
                col  = COLORS[i]
                scatter_p = pg.ScatterPlotItem(
                    x=p_re, y=p_im, symbol="x", size=12,
                    pen=pg.mkPen(col, width=2), brush=pg.mkBrush(None),
                    name=f"poles {label}",
                )
                pi.addItem(scatter_p)
                if z_re:
                    scatter_z = pg.ScatterPlotItem(
                        x=z_re, y=z_im, symbol="o", size=10,
                        pen=pg.mkPen(col, width=1.5), brush=pg.mkBrush(None),
                        name=f"zeros {label}",
                    )
                    pi.addItem(scatter_z)

        add_vline(pi, 0.0, "#888888", width=0.6)
        add_hline(pi, 0.0, "#888888", width=0.6)
        pi.addLegend()


# ── Formatting helpers ────────────────────────────────────────

def _as_float(val) -> float | None:
    """Numeric value of a Routh cell, or None if it stayed symbolic."""
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _routh_cell_text(result, val) -> str:
    """
    Display text for one Routh cell.

    A symbolic entry is simplified for readability; a numeric one is shown to
    5 significant figures. Only conversion is attempted here — anything that
    fails falls back to the raw repr rather than losing the cell, since a
    single awkward expression should not blank the table.
    """
    if result.is_symbolic:
        try:
            return str(sp.simplify(val))
        except (TypeError, ValueError, AttributeError):
            return str(val)
    fv = _as_float(val)
    return f"{fv:.5g}" if fv is not None else str(val)

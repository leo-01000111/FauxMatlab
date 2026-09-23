"""
System tab — poles/zeros, factored form, stability summary.
"""

from __future__ import annotations

import numpy as np
import control as ctl
from PySide6.QtCore    import Qt
from PySide6.QtGui     import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QGroupBox,
    QComboBox, QSplitter, QSizePolicy,
)

from ..guard import GuardedPanel, guard
from ..plots import make_plot, draw_pz_map, apply_theme
from ...core.architecture import CourseArchitecture
from ...core.tf_utils     import analyse, factored_str, coefficients_str


class SystemTab(QWidget, GuardedPanel):

    def __init__(self, arch: CourseArchitecture, parent=None) -> None:
        super().__init__(parent)
        self._arch = arch
        self._build_ui()
        self.refresh()

    # ── UI ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.install_error_banner(root)

        # Signal selector
        sel_row = QHBoxLayout()
        sel_row.addWidget(QLabel("Analyse:"))
        self._sig_combo = QComboBox()
        self._sig_combo.addItems([
            "Open-loop plant G(s)",
            "Loop TF  L = K₂G",
            "Sensitivity  S",
            "Compl. Sensitivity  T",
            "r → y (closed loop)",
            "r → u",
            "r → e",
            "di → y",
            "do → y",
            "n → y",
        ])
        self._sig_combo.currentIndexChanged.connect(lambda _: self.refresh())
        sel_row.addWidget(self._sig_combo)
        sel_row.addStretch()
        root.addLayout(sel_row)

        splitter = QSplitter(Qt.Horizontal)

        # Left: tables + info
        left = QWidget()
        left_lay = QVBoxLayout(left)

        self._tf_label = QLabel("")
        self._tf_label.setWordWrap(True)
        self._tf_label.setFont(QFont("Courier New", 10))
        left_lay.addWidget(self._tf_label)

        self._info_label = QLabel("")
        self._info_label.setWordWrap(True)
        left_lay.addWidget(self._info_label)

        # Poles table
        grp_poles = QGroupBox("Poles")
        pl_lay = QVBoxLayout(grp_poles)
        self._poles_table = _make_table(
            ["Pole", "Re", "Im", "ωn", "ζ", "τ", "Kind"])
        pl_lay.addWidget(self._poles_table)
        left_lay.addWidget(grp_poles)

        # Zeros table
        grp_zeros = QGroupBox("Zeros")
        zl_lay = QVBoxLayout(grp_zeros)
        self._zeros_table = _make_table(["Zero", "Re", "Im"])
        zl_lay.addWidget(self._zeros_table)
        left_lay.addWidget(grp_zeros)

        splitter.addWidget(left)

        # Right: pole-zero map
        right = QWidget()
        right_lay = QVBoxLayout(right)
        self._pz_plot = make_plot("Poles & Zeros (s-plane)",
                                  "Re(s)", "Im(s)")
        right_lay.addWidget(self._pz_plot)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter)

    # ── Refresh ───────────────────────────────────────────────

    @guard("Analysis")
    def refresh(self, arch: CourseArchitecture | None = None) -> None:
        if arch is not None:
            self._arch = arch
        tf = self._selected_tf()
        if tf is None:
            return

        info = analyse(tf)

        # Factored form
        self._tf_label.setText(
            f"G(s) = {factored_str(tf)}"
        )

        # Info badges
        stab  = "✓ Stable"     if info.stable         else "✗ Unstable"
        mp    = "Min-phase"    if info.minimum_phase   else "Non-min-phase"
        dc    = f"{info.dc_gain:.5g}" if not np.isinf(info.dc_gain) else "∞"
        self._info_label.setText(
            f"{stab}  |  {mp}  |  DC gain = {dc}  "
            f"|  Order = {info.order}  |  Type = {info.system_type}"
        )

        # Poles table
        self._poles_table.setRowCount(len(info.poles))
        for row, pi in enumerate(info.poles):
            self._poles_table.setItem(row, 0, _item(_fmt_cplx(pi.value)))
            self._poles_table.setItem(row, 1, _item(f"{pi.real:.5g}"))
            self._poles_table.setItem(row, 2, _item(f"{pi.imag:.5g}"))
            self._poles_table.setItem(row, 3, _item(f"{pi.wn:.5g}"))
            self._poles_table.setItem(row, 4, _item(_fmt_f(pi.zeta)))
            self._poles_table.setItem(row, 5, _item(_fmt_f(pi.tau)))
            self._poles_table.setItem(row, 6, _item(pi.kind))

        # Zeros table
        self._zeros_table.setRowCount(len(info.zeros))
        for row, z in enumerate(info.zeros):
            self._zeros_table.setItem(row, 0, _item(_fmt_cplx(z)))
            self._zeros_table.setItem(row, 1, _item(f"{z.real:.5g}"))
            self._zeros_table.setItem(row, 2, _item(f"{z.imag:.5g}"))

        # Pole-zero map
        pi_plot = self._pz_plot.getPlotItem()
        pi_plot.clear()
        apply_theme(pi_plot, "Poles & Zeros (s-plane)", "Re(s)", "Im(s)")
        draw_pz_map(pi_plot, [p.value for p in info.poles], info.zeros)

    # ── Internal ──────────────────────────────────────────────

    def _selected_tf(self) -> ctl.TransferFunction | None:
        """The transfer function the selector names. Failures propagate to
        @guard on refresh() rather than blanking the tab."""
        getters = [
            self._arch.open_loop_tf,
            self._arch.loop_tf,
            self._arch.sensitivity,
            self._arch.compl_sensitivity,
            lambda: self._arch.get_closed_loop_tf("r",  "y"),
            lambda: self._arch.get_closed_loop_tf("r",  "u"),
            lambda: self._arch.get_closed_loop_tf("r",  "e"),
            lambda: self._arch.get_closed_loop_tf("di", "y"),
            lambda: self._arch.get_closed_loop_tf("do", "y"),
            lambda: self._arch.get_closed_loop_tf("n",  "y"),
        ]
        idx = self._sig_combo.currentIndex()
        return getters[idx]() if 0 <= idx < len(getters) else None

    def set_active_signal(self, signal_id: str) -> None:
        """Sync the selector when the user clicks a diagram signal."""
        mapping = {
            "r": 4, "u": 5, "e": 6, "di": 7, "do": 8, "n": 9,
            "y": 4,
        }
        if signal_id in mapping:
            self._sig_combo.setCurrentIndex(mapping[signal_id])


# ── Helpers ───────────────────────────────────────────────────

def _make_table(headers: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QTableWidget.NoEditTriggers)
    t.horizontalHeader().setStretchLastSection(True)
    t.setAlternatingRowColors(True)
    t.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    t.setMaximumHeight(160)
    return t


def _item(text: str) -> QTableWidgetItem:
    it = QTableWidgetItem(text)
    it.setTextAlignment(Qt.AlignCenter)
    return it


def _fmt_cplx(z: complex) -> str:
    if abs(z.imag) < 1e-8:
        return f"{z.real:.5g}"
    sign = "+" if z.imag >= 0 else "−"
    return f"{z.real:.4g} {sign} {abs(z.imag):.4g}j"


def _fmt_f(v: float) -> str:
    if np.isnan(v):   return "N/A"
    if np.isinf(v):   return "∞"
    return f"{v:.4g}"

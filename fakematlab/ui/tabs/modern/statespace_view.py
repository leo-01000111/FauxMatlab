"""
State Space view: edit A/B/C/D, convert, change coordinates, see the modes.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ....core.statespace import (
    StateSpaceError,
    analyse,
    controllable_form,
    minimal,
    modal_form,
    modal_response,
    observable_form,
    state_space,
    to_tf,
)
from ....core.tf_utils import factored_str
from ...guard import GuardedPanel, guard
from ...plots import apply_theme, curve_pen, draw_pz_map, make_plot
from .widgets import MatrixEditor, frame_poles, make_table, parse_matrix, table_item


class StateSpaceView(QWidget, GuardedPanel):
    """A/B/C/D, eigenvalues, modes, and the modal decomposition."""

    def __init__(self, context, parent=None) -> None:
        super().__init__(parent)
        self.ctx = context
        self._build_ui()
        self.ctx.model_changed.connect(self.refresh)
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(2, 2, 2, 2)
        self.install_error_banner(root)

        splitter = QSplitter(Qt.Horizontal)

        # ── left: the matrices ──
        left = QWidget()
        left.setMaximumWidth(400)
        left.setMinimumWidth(0)
        left_lay = QVBoxLayout(left)

        grp = QGroupBox("ẋ = Ax + Bu,   y = Cx + Du")
        grp_lay = QVBoxLayout(grp)
        self._editor = MatrixEditor()
        self._editor.applied.connect(self._apply_matrices)
        grp_lay.addWidget(self._editor)
        left_lay.addWidget(grp)

        convert = QGroupBox("Convert")
        conv_lay = QVBoxLayout(convert)
        row = QHBoxLayout()
        self._form_combo = QComboBox()
        self._form_combo.addItems(["controllable", "observable", "modal"])
        row.addWidget(QLabel("Canonical form:"))
        row.addWidget(self._form_combo)
        apply_form = QPushButton("Apply")
        apply_form.clicked.connect(self._apply_form)
        row.addWidget(apply_form)
        conv_lay.addLayout(row)

        minimise = QPushButton("Minimal realisation")
        minimise.setToolTip(
            "Remove states that are uncontrollable or unobservable — the "
            "modes the transfer function cannot see.")
        minimise.clicked.connect(self._minimise)
        conv_lay.addWidget(minimise)
        left_lay.addWidget(convert)

        self._tf_label = QLabel("")
        self._tf_label.setWordWrap(True)
        self._tf_label.setFont(QFont("Consolas", 9))
        self._tf_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        left_lay.addWidget(self._tf_label)

        self._info = QLabel("")
        self._info.setWordWrap(True)
        left_lay.addWidget(self._info)
        left_lay.addStretch()
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QScrollArea.NoFrame)
        left_scroll.setWidget(left)
        left_scroll.setMaximumWidth(420)
        splitter.addWidget(left_scroll)

        # ── right: modes and plots ──
        right = QSplitter(Qt.Vertical)

        mode_box = QGroupBox("Modes")
        mode_lay = QVBoxLayout(mode_box)
        self._modes = make_table(
            ["λ", "ωn", "ζ", "τ", "input coupling", "output coupling",
             "|residue|", "visible?"])
        mode_lay.addWidget(self._modes)
        right.addWidget(mode_box)

        plots = QWidget()
        plot_lay = QHBoxLayout(plots)
        self._pz = make_plot("Eigenvalues (s-plane)", "Re", "Im")
        plot_lay.addWidget(self._pz)
        self._modal = make_plot("Free response, split by mode",
                                "Time (s)", "y")
        plot_lay.addWidget(self._modal)
        right.addWidget(plots)

        right.setStretchFactor(0, 1)
        right.setStretchFactor(1, 2)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, stretch=1)

    # ── actions ─────────────────────────────────────────────────

    @guard("Apply matrices")
    def _apply_matrices(self, a_text: str, b_text: str,
                        c_text: str, d_text: str) -> None:
        matrices = [parse_matrix(text)
                    for text in (a_text, b_text, c_text, d_text)]
        self.ctx.set_system(state_space(*matrices), "edited by hand")

    @guard("Canonical form")
    def _apply_form(self) -> None:
        form = self._form_combo.currentText()
        builder = {"controllable": controllable_form,
                   "observable": observable_form,
                   "modal": modal_form}[form]
        self.ctx.set_system(builder(self.ctx.sys), f"{form} canonical form")

    @guard("Minimal realisation")
    def _minimise(self) -> None:
        before = self.ctx.sys.nstates
        reduced = minimal(self.ctx.sys)
        if reduced.nstates == before:
            self.ctx.status.emit(
                f"already minimal — all {before} states are controllable and "
                f"observable")
            return
        self.ctx.set_system(reduced, "minimal realisation")
        self.ctx.status.emit(
            f"reduced from {before} to {reduced.nstates} states")

    # ── refresh ─────────────────────────────────────────────────

    @guard("State-space analysis")
    def refresh(self, *_ignored) -> None:
        sys = self.ctx.sys
        self._editor.set_matrices(sys.A, sys.B, sys.C, sys.D)

        info = analyse(sys)
        self._tf_label.setText("G(s) = " + factored_str(to_tf(sys)))
        self._info.setText(info.summary())

        self._fill_modes(info)
        self._draw_pz(info)
        self._draw_modal(sys)

    def _fill_modes(self, info) -> None:
        self._modes.setRowCount(len(info.modes))
        for row, mode in enumerate(info.modes):
            values = [
                _fmt_complex(mode.eigenvalue),
                f"{mode.info.wn:.4g}",
                _fmt(mode.info.zeta),
                _fmt(mode.info.tau),
                _fmt(mode.input_coupling),
                _fmt(mode.output_coupling),
                _fmt(abs(mode.residue)),
                "yes" if mode.visible else "NO — hidden",
            ]
            for col, text in enumerate(values):
                item = table_item(text)
                if not mode.visible:
                    item.setForeground(Qt.red)
                self._modes.setItem(row, col, item)

    def _draw_pz(self, info) -> None:
        plot = self._pz.getPlotItem()
        plot.clear()
        apply_theme(plot, "Eigenvalues (s-plane)", "Re", "Im")
        draw_pz_map(plot, [complex(v) for v in info.eigenvalues],
                    [complex(z) for z in np.atleast_1d(info.transmission_zeros)])
        frame_poles(plot, list(info.eigenvalues)
                    + list(np.atleast_1d(info.transmission_zeros)))

    def _draw_modal(self, sys) -> None:
        plot = self._modal.getPlotItem()
        plot.clear()
        apply_theme(plot, "Free response, split by mode", "Time (s)", "y")
        plot.addLegend(offset=(-10, 10))

        eigenvalues = np.linalg.eigvals(np.asarray(sys.A))
        slowest = min((abs(v.real) for v in eigenvalues if abs(v.real) > 1e-9),
                      default=1.0)
        t = np.linspace(0.0, min(8.0 / slowest, 200.0), 600)

        try:
            parts = modal_response(sys, t)
        except StateSpaceError as exc:
            # A defective A has no modal split; say so on the plot rather than
            # leaving it blank.
            plot.setTitle(f"Cannot split into modes — {exc}", color="#F4A261")
            return

        total = parts.pop("total")
        for i, (name, curve) in enumerate(parts.items()):
            plot.plot(t, curve, pen=curve_pen(i + 1, 1.4), name=name)
        plot.plot(t, total, pen=curve_pen(0, 2.4), name="total")


def _fmt(v: float) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    if np.isinf(v):
        return "∞"
    return f"{v:.4g}"


def _fmt_complex(z: complex) -> str:
    if abs(z.imag) < 1e-10:
        return f"{z.real:.5g}"
    sign = "+" if z.imag >= 0 else "−"
    return f"{z.real:.4g} {sign} {abs(z.imag):.4g}j"

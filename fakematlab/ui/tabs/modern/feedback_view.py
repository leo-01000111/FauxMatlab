"""
State Feedback view: pole placement and LQR, with the control effort shown.
"""

from __future__ import annotations

import control as ctl
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ....core.statefbk import DesignError, acker, control_effort, lqi, lqr, place
from ...guard import GuardedPanel, guard
from ...plots import add_hline, apply_theme, curve_pen, make_plot
from .widgets import fill_table, frame_poles, make_table


class FeedbackView(QWidget, GuardedPanel):
    """Design ``u = −Kx`` by placing poles or by weighting a cost."""

    def __init__(self, context, parent=None) -> None:
        super().__init__(parent)
        self.ctx = context
        self._design = None
        self._build_ui()
        self.ctx.model_changed.connect(self._on_model_changed)
        self._on_model_changed()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(2, 2, 2, 2)
        self.install_error_banner(root)

        splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        left.setMaximumWidth(380)
        left_lay = QVBoxLayout(left)

        # ── pole placement ──
        place_box = QGroupBox("Pole placement")
        place_lay = QVBoxLayout(place_box)
        self._poles = QLineEdit()
        self._poles.setPlaceholderText("-2, -3   (one per state)")
        place_lay.addWidget(self._poles)
        row = QHBoxLayout()
        for label, method in (("place (robust)", "place"),
                              ("Ackermann", "acker")):
            button = QPushButton(label)
            button.clicked.connect(
                lambda _checked=False, m=method: self._place(m))
            row.addWidget(button)
        place_lay.addLayout(row)
        place_lay.addWidget(QLabel(
            "Robust placement conditions the eigenvectors; Ackermann is the\n"
            "closed form the course derives. Same poles, different gains."))
        left_lay.addWidget(place_box)

        # ── LQR ──
        lqr_box = QGroupBox("LQR:  min ∫ xᵀQx + uᵀRu")
        lqr_lay = QVBoxLayout(lqr_box)
        self._q = QLineEdit("1")
        self._q.setPlaceholderText("scalar, or one weight per state")
        lqr_lay.addWidget(_labelled("Q (state weight):", self._q))

        self._r_slider = QSlider(Qt.Horizontal)
        self._r_slider.setRange(-40, 40)        # log10(R) × 10
        self._r_slider.setValue(0)
        self._r_slider.valueChanged.connect(self._on_r_changed)
        self._r_label = QLabel("R = 1")
        lqr_lay.addWidget(self._r_label)
        lqr_lay.addWidget(self._r_slider)
        lqr_lay.addWidget(QLabel(
            "Drag R: small R buys speed with control effort,\n"
            "large R buys economy with sluggishness."))

        self._integral = QCheckBox("Add integral action (LQI)")
        self._integral.setToolTip(
            "Augments the state with ∫(r−y)dt, which removes steady-state "
            "error even when the model is wrong — Nbar alone cannot.")
        lqr_lay.addWidget(self._integral)

        design_button = QPushButton("Design LQR")
        design_button.clicked.connect(self._lqr)
        lqr_lay.addWidget(design_button)
        left_lay.addWidget(lqr_box)

        self._result = QLabel("")
        self._result.setWordWrap(True)
        self._result.setFont(QFont("Consolas", 9))
        self._result.setTextInteractionFlags(Qt.TextSelectableByMouse)
        left_lay.addWidget(self._result)
        left_lay.addStretch()
        splitter.addWidget(left)

        # ── right ──
        right = QSplitter(Qt.Vertical)

        table_box = QGroupBox("Open loop vs closed loop")
        table_lay = QVBoxLayout(table_box)
        self._table = make_table(["", "eigenvalues", "ωn", "ζ"],
                                 max_height=150)
        table_lay.addWidget(self._table)
        right.addWidget(table_box)

        plots = QWidget()
        plot_lay = QHBoxLayout(plots)
        self._pz = make_plot("Eigenvalues", "Re", "Im")
        plot_lay.addWidget(self._pz)
        self._response = make_plot("Step response and control effort",
                                   "Time (s)", "")
        plot_lay.addWidget(self._response)
        right.addWidget(plots)

        right.setStretchFactor(0, 1)
        right.setStretchFactor(1, 2)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, stretch=1)

    # ── model changes ───────────────────────────────────────────

    def _on_model_changed(self) -> None:
        n = self.ctx.n
        # A sensible default: poles a little left of the existing ones.
        existing = np.linalg.eigvals(np.asarray(self.ctx.sys.A))
        spread = max((abs(v) for v in existing), default=1.0) or 1.0
        default = [-spread * (1.0 + 0.5 * i) for i in range(n)]
        self._poles.setText(", ".join(f"{p:.3g}" for p in default))
        self._design = None
        self._clear_plots()

    def _on_r_changed(self, value: int) -> None:
        self._r_label.setText(f"R = {10 ** (value / 10.0):.4g}")
        if self._design is not None and "LQR" in self._design.method:
            self._lqr()

    # ── designs ─────────────────────────────────────────────────

    @guard("Pole placement")
    def _place(self, method: str) -> None:
        text = self._poles.text()
        try:
            desired = [complex(p.strip().replace("i", "j"))
                       for p in text.split(",") if p.strip()]
        except ValueError as exc:
            raise DesignError(
                f"could not read the pole list {text!r}: {exc}. "
                f"Use comma-separated numbers, e.g. '-2, -3', or "
                f"'-1+2j, -1-2j' for a complex pair."
            ) from exc

        builder = acker if method == "acker" else place
        self._show(builder(self.ctx.sys, desired))

    @guard("LQR design")
    def _lqr(self) -> None:
        R = 10 ** (self._r_slider.value() / 10.0)
        Q = _parse_weights(self._q.text(), "Q")
        design = (lqi(self.ctx.sys, None, R) if self._integral.isChecked()
                  else lqr(self.ctx.sys, Q, R))
        self._show(design)

    def _show(self, design) -> None:
        self._design = design
        self._result.setText(design.summary())
        self.ctx.set_feedback(design.K)
        self._fill_table(design)
        self._draw(design)

    # ── display ─────────────────────────────────────────────────

    def _fill_table(self, design) -> None:
        rows = []
        for label, values in (("open loop",
                               np.linalg.eigvals(np.asarray(self.ctx.sys.A))),
                              ("closed loop", design.eigenvalues)):
            for value in values:
                wn = abs(value)
                zeta = -value.real / wn if wn > 1e-12 else float("nan")
                rows.append([label, _fmt_complex(value), f"{wn:.4g}",
                             "—" if np.isnan(zeta) else f"{zeta:.4g}"])
                label = ""
        fill_table(self._table, rows)

    def _draw(self, design) -> None:
        pz = self._pz.getPlotItem()
        pz.clear()
        apply_theme(pz, "Eigenvalues", "Re", "Im")
        pz.addLegend(offset=(-10, 10))
        open_loop = np.linalg.eigvals(np.asarray(self.ctx.sys.A))
        pz.plot([v.real for v in open_loop], [v.imag for v in open_loop],
                pen=None, symbol="x", symbolSize=13,
                symbolPen=curve_pen(1, 2.0), name="open loop")
        pz.plot([v.real for v in design.eigenvalues],
                [v.imag for v in design.eigenvalues],
                pen=None, symbol="o", symbolSize=11,
                symbolPen=curve_pen(0, 2.0), name="closed loop")
        add_hline(pz, 0.0, "#888888", width=0.6)
        frame_poles(pz, list(design.eigenvalues) + list(
            np.linalg.eigvals(np.asarray(self.ctx.sys.A))))

        response = self._response.getPlotItem()
        response.clear()
        apply_theme(response, "Step response and control effort",
                    "Time (s)", "")
        response.addLegend(offset=(-10, 10))

        slowest = min((abs(v.real) for v in design.eigenvalues
                       if abs(v.real) > 1e-9), default=1.0)
        t = np.linspace(0.0, min(8.0 / slowest, 200.0), 600)

        # An LQI design has an extra integrator state, so its K does not fit
        # the original plant; show the augmented closed loop instead.
        if design.K.shape[1] != self.ctx.n:
            _, y = ctl.step_response(design.closed_loop, T=t)
            response.plot(t, np.atleast_2d(y)[0], pen=curve_pen(0, 2.2),
                          name="y (with integral action)")
            add_hline(response, 1.0, "#888888", width=0.6)
            return

        y, u = control_effort(self.ctx.sys, design.K, design.Nbar, t)
        response.plot(t, y, pen=curve_pen(0, 2.2), name="y")
        response.plot(t, u, pen=curve_pen(3, 1.6), name="u (control effort)")
        add_hline(response, 1.0, "#888888", width=0.6)

    def _clear_plots(self) -> None:
        for widget, title in ((self._pz, "Eigenvalues"),
                              (self._response,
                               "Step response and control effort")):
            plot = widget.getPlotItem()
            plot.clear()
            apply_theme(plot, title, "", "")
        self._table.setRowCount(0)
        self._result.setText("")


def _labelled(text: str, widget) -> QWidget:
    holder = QWidget()
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    row.addWidget(QLabel(text))
    row.addWidget(widget)
    return holder


def _parse_weights(text: str, name: str):
    values = [float(v) for v in text.replace(",", " ").split() if v.strip()]
    if not values:
        raise DesignError(f"{name} needs at least one number")
    return values[0] if len(values) == 1 else np.diag(values)


def _fmt_complex(z: complex) -> str:
    if abs(z.imag) < 1e-10:
        return f"{z.real:.5g}"
    sign = "+" if z.imag >= 0 else "−"
    return f"{z.real:.4g} {sign} {abs(z.imag):.4g}j"

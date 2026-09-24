"""
Observer view: Luenberger, reduced-order, Kalman, and the separation principle.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ....core.observers import (
    compensator,
    estimation_error_response,
    kalman,
    observer,
    reduced_observer,
)
from ....core.statefbk import DesignError
from ...guard import GuardedPanel, guard
from ...plots import add_hline, apply_theme, curve_pen, make_plot
from .widgets import fill_table, frame_poles, make_table


class ObserverView(QWidget, GuardedPanel):
    """Estimate the state you cannot measure."""

    def __init__(self, context, parent=None) -> None:
        super().__init__(parent)
        self.ctx = context
        self._design = None
        self._build_ui()
        self.ctx.model_changed.connect(self._on_model_changed)
        self.ctx.feedback_changed.connect(lambda _K: self._refresh_separation())
        self._on_model_changed()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(2, 2, 2, 2)
        self.install_error_banner(root)

        splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        left.setMaximumWidth(380)
        left.setMinimumWidth(0)
        left_lay = QVBoxLayout(left)

        place_box = QGroupBox("Luenberger observer")
        place_lay = QVBoxLayout(place_box)
        self._poles = QLineEdit()
        self._poles.setPlaceholderText("-10, -11   (one per state)")
        place_lay.addWidget(self._poles)
        row = QHBoxLayout()
        full = QPushButton("Full order")
        full.clicked.connect(self._full)
        row.addWidget(full)
        reduced = QPushButton("Reduced order")
        reduced.setToolTip(
            "Estimate only the states you do not measure: smaller and faster, "
            "but it passes sensor noise straight through.")
        reduced.clicked.connect(self._reduced)
        row.addWidget(reduced)
        place_lay.addLayout(row)
        place_lay.addWidget(QLabel(
            "Rule of thumb: 2–5× faster than the controller poles, so the\n"
            "estimate has settled before the feedback acts on it."))
        left_lay.addWidget(place_box)

        kalman_box = QGroupBox("Kalman filter")
        kalman_lay = QVBoxLayout(kalman_box)
        self._v_slider = QSlider(Qt.Horizontal)
        self._v_slider.setRange(-40, 40)
        self._v_slider.setValue(0)
        self._v_slider.valueChanged.connect(self._on_v_changed)
        self._v_label = QLabel("measurement noise V = 1")
        kalman_lay.addWidget(self._v_label)
        kalman_lay.addWidget(self._v_slider)
        kalman_lay.addWidget(QLabel(
            "Large V means a sensor you do not trust, so the filter leans\n"
            "on its model and responds slowly."))
        design = QPushButton("Design Kalman filter")
        design.clicked.connect(self._kalman)
        kalman_lay.addWidget(design)
        left_lay.addWidget(kalman_box)

        self._result = QLabel("")
        self._result.setWordWrap(True)
        self._result.setFont(QFont("Consolas", 9))
        self._result.setTextInteractionFlags(Qt.TextSelectableByMouse)
        left_lay.addWidget(self._result)
        left_lay.addStretch()
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QScrollArea.NoFrame)
        left_scroll.setWidget(left)
        left_scroll.setMaximumWidth(400)
        splitter.addWidget(left_scroll)

        right = QSplitter(Qt.Vertical)

        sep_box = QGroupBox("Separation principle")
        sep_lay = QVBoxLayout(sep_box)
        self._separation = QLabel(
            "Design a state feedback on the Feedback tab as well, and the "
            "combined closed-loop poles appear here.")
        self._separation.setWordWrap(True)
        self._separation.setFont(QFont("Consolas", 9))
        sep_lay.addWidget(self._separation)
        self._poles_table = make_table(["source", "pole"], max_height=150)
        sep_lay.addWidget(self._poles_table)
        right.addWidget(sep_box)

        plots = QWidget()
        plot_lay = QHBoxLayout(plots)
        self._pz = make_plot("Estimation-error eigenvalues", "Re", "Im")
        plot_lay.addWidget(self._pz)
        self._error = make_plot("Estimation error decay", "Time (s)", "e")
        plot_lay.addWidget(self._error)
        right.addWidget(plots)

        right.setStretchFactor(0, 1)
        right.setStretchFactor(1, 2)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, stretch=1)

    # ── model changes ───────────────────────────────────────────

    def _on_model_changed(self) -> None:
        existing = np.linalg.eigvals(np.asarray(self.ctx.sys.A))
        spread = max((abs(v) for v in existing), default=1.0) or 1.0
        default = [-5.0 * spread * (1.0 + 0.2 * i)
                   for i in range(self.ctx.n)]
        self._poles.setText(", ".join(f"{p:.3g}" for p in default))
        self._design = None
        self._result.setText("")
        self._poles_table.setRowCount(0)

    def _on_v_changed(self, value: int) -> None:
        self._v_label.setText(
            f"measurement noise V = {10 ** (value / 10.0):.4g}")
        if self._design is not None and "Kalman" in self._design.method:
            self._kalman()

    # ── designs ─────────────────────────────────────────────────

    def _requested(self, count: int) -> list[complex]:
        text = self._poles.text()
        try:
            values = [complex(p.strip().replace("i", "j"))
                      for p in text.split(",") if p.strip()]
        except ValueError as exc:
            raise DesignError(
                f"could not read the pole list {text!r}: {exc}") from exc
        return values[:count] if count < len(values) else values

    @guard("Observer design")
    def _full(self) -> None:
        self._show(observer(self.ctx.sys, self._requested(self.ctx.n)))

    @guard("Reduced observer design")
    def _reduced(self) -> None:
        outputs = np.atleast_2d(np.asarray(self.ctx.sys.C)).shape[0]
        self._show(reduced_observer(
            self.ctx.sys, self._requested(self.ctx.n - outputs)))

    @guard("Kalman filter")
    def _kalman(self) -> None:
        V = 10 ** (self._v_slider.value() / 10.0)
        self._show(kalman(self.ctx.sys, None, V))

    def _show(self, design) -> None:
        self._design = design
        self._result.setText(design.summary())
        # A reduced observer's L has fewer rows than the plant has states, so
        # it is not a drop-in for the separation-principle assembly.
        full_order = design.L.shape[0] == self.ctx.n
        self.ctx.set_observer(design.L if full_order else None)
        self._draw(design, full_order)
        self._refresh_separation()

    # ── display ─────────────────────────────────────────────────

    def _draw(self, design, full_order: bool) -> None:
        pz = self._pz.getPlotItem()
        pz.clear()
        apply_theme(pz, "Estimation-error eigenvalues", "Re", "Im")
        pz.addLegend(offset=(-10, 10))
        plant = np.linalg.eigvals(np.asarray(self.ctx.sys.A))
        pz.plot([v.real for v in plant], [v.imag for v in plant],
                pen=None, symbol="x", symbolSize=13,
                symbolPen=curve_pen(1, 2.0), name="plant")
        pz.plot([v.real for v in design.eigenvalues],
                [v.imag for v in design.eigenvalues],
                pen=None, symbol="o", symbolSize=11,
                symbolPen=curve_pen(2, 2.0), name="A − LC")
        add_hline(pz, 0.0, "#888888", width=0.6)
        frame_poles(pz, list(design.eigenvalues) + list(
            np.linalg.eigvals(np.asarray(self.ctx.sys.A))))

        error = self._error.getPlotItem()
        error.clear()
        apply_theme(error, "Estimation error decay", "Time (s)", "e")
        if not full_order:
            error.setTitle(
                "Reduced observer: the measured states have no error to show",
                color="#F4A261")
            return

        error.addLegend(offset=(-10, 10))
        slowest = min((abs(v.real) for v in design.eigenvalues
                       if abs(v.real) > 1e-9), default=1.0)
        t = np.linspace(0.0, min(8.0 / slowest, 200.0), 500)
        curves = estimation_error_response(self.ctx.sys, design.L, t)
        for i, curve in enumerate(curves):
            error.plot(t, curve, pen=curve_pen(i, 1.8), name=f"e{i}")
        add_hline(error, 0.0, "#888888", width=0.6)

    def _refresh_separation(self) -> None:
        K, L = self.ctx.K, self.ctx.L
        if K is None or L is None:
            self._separation.setText(
                "Design a state feedback on the Feedback tab as well, and the "
                "combined closed-loop poles appear here.")
            self._poles_table.setRowCount(0)
            return
        if K.shape[1] != self.ctx.n or L.shape[0] != self.ctx.n:
            self._separation.setText(
                "The current K or L does not match this plant's state "
                "dimension — redesign both.")
            self._poles_table.setRowCount(0)
            return

        try:
            comp = compensator(self.ctx.sys, K, L)
        except Exception as exc:                       # noqa: BLE001
            self._separation.setText(f"⚠ {exc}")
            return

        self._separation.setText(
            comp.summary() + "\n\nThe two designs do not interact: the closed-"
            "loop poles are exactly the union of the controller's and the "
            "observer's.")
        rows = ([["controller", _fmt_complex(p)] for p in comp.control_poles]
                + [["observer", _fmt_complex(p)] for p in comp.observer_poles])
        fill_table(self._poles_table, rows)


def _fmt_complex(z: complex) -> str:
    if abs(z.imag) < 1e-10:
        return f"{z.real:.5g}"
    sign = "+" if z.imag >= 0 else "−"
    return f"{z.real:.4g} {sign} {abs(z.imag):.4g}j"

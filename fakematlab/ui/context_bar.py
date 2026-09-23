"""
The model context bar: what is loaded, and whether it is stable.

This replaces the permanent 420–760 px left column as the app's answer to
"what am I looking at". That column showed the architecture diagram and a
block editor on *every* tab — 21 % of the window, including on the two tabs
that analyse a different model entirely — while the only always-visible
summary of the system was a status line reading

    G=[1, 2]/[1, 3, 3, 1]   K₂=[4]/[1]

which is a pair of coefficient arrays, not a transfer function, and says
nothing about stability.

The bar shows factored transfer functions, an internal-stability verdict and
the headline margins, in one strip across the top. The diagram and the block
editor move into a dock that opens on demand.
"""

from __future__ import annotations

import control as ctl
import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from ..core.architecture import CourseArchitecture
from ..core.freqresp import bode
from ..core.tf_utils import factored_str
from .design import NORMAL, SECTION, TIGHT, MetricLabel, Status, StatusBadge, monospace


class ContextBar(QFrame):
    """One strip: the plant, the controller, the verdict, the margins."""

    #: The user asked to see the block editor.
    edit_requested = Signal()

    def __init__(self, arch: CourseArchitecture, parent=None) -> None:
        super().__init__(parent)
        self._arch = arch
        self.setFrameShape(QFrame.StyledPanel)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(SECTION, TIGHT, SECTION, TIGHT)
        outer.setSpacing(SECTION)

        # ── the systems ──
        systems = QVBoxLayout()
        systems.setSpacing(0)
        self._plant = QLabel("")
        self._plant.setFont(monospace())
        self._plant.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._plant.setAccessibleName("plant transfer function")
        systems.addWidget(self._plant)

        self._controller = QLabel("")
        self._controller.setFont(monospace())
        self._controller.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._controller.setAccessibleName("controller transfer function")
        systems.addWidget(self._controller)
        outer.addLayout(systems)

        outer.addWidget(_divider())

        # ── the verdict ──
        self._badge = StatusBadge()
        outer.addWidget(self._badge)

        self._note = QLabel("")
        self._note.setStyleSheet("color: palette(mid);")
        self._note.setWordWrap(True)
        outer.addWidget(self._note, stretch=1)

        # ── headline margins ──
        self._pm = MetricLabel("PM", "°")
        self._gm = MetricLabel("GM", "dB")
        self._wc = MetricLabel("ωc", "rad/s")
        for metric in (self._pm, self._gm, self._wc):
            outer.addWidget(metric)

        outer.addWidget(_divider())

        self._edit_btn = QPushButton("Edit model ▾")
        self._edit_btn.setToolTip(
            "Show the architecture diagram and the block editor (Ctrl+\\)")
        self._edit_btn.clicked.connect(self.edit_requested)
        outer.addWidget(self._edit_btn)

        self.refresh()

    # ── state ───────────────────────────────────────────────────

    def set_architecture(self, arch: CourseArchitecture) -> None:
        self._arch = arch
        self.refresh()

    def refresh(self, *_ignored) -> None:
        """
        Recompute the summary.

        Guarded by hand rather than with ``@guard``: this bar is chrome, and a
        bar that replaces itself with an error banner because a margin could
        not be computed is worse than one that says so in its own fields.
        """
        try:
            self._plant.setText(f"G(s)  = {factored_str(self._arch.block_tf('G'))}")
            self._controller.setText(
                f"K₂(s) = {factored_str(self._arch.block_tf('K2'))}")
        except Exception as exc:                                # noqa: BLE001
            self._plant.setText("G(s)  = —")
            self._controller.setText(f"K₂(s) = — ({type(exc).__name__})")

        self._refresh_verdict()
        self._refresh_margins()

    def _refresh_verdict(self) -> None:
        try:
            report = self._arch.internal_stability()
        except Exception as exc:                                # noqa: BLE001
            self._badge.set_status(Status.ERROR, "stability unknown")
            self._note.setText(f"{type(exc).__name__}: {exc}")
            return

        if not report.stable:
            worst = max((m.real for m in report.unstable_modes), default=0.0)
            self._badge.set_status(Status.CRITICAL, "unstable")
            hidden = len(report.unstable_hidden)
            self._note.setText(
                f"{len(report.unstable_modes)} mode(s) in the right half "
                f"plane, fastest Re = {worst:+.3g}"
                + (f" — {hidden} of them hidden from every port"
                   if hidden else ""))
        elif report.cancellations:
            self._badge.set_status(Status.WARNING, "stable, with cancellation")
            self._note.setText(
                f"{len(report.cancellations)} pole–zero cancellation(s); "
                f"the loop is internally stable but a mode is invisible.")
        else:
            self._badge.set_status(Status.OK, "stable")
            self._note.setText("")

    def _refresh_margins(self) -> None:
        try:
            data = bode(self._arch.loop_tf())
        except Exception:                                       # noqa: BLE001
            for metric in (self._pm, self._gm, self._wc):
                metric.set_undefined("the loop response could not be computed")
            return

        if np.isfinite(data.wc) and data.wc > 0:
            self._pm.set_value(data.pm_deg, "{:.1f}")
            self._wc.set_value(data.wc)
        else:
            why = ("the loop never crosses 0 dB, so there is no gain "
                   "crossover to measure a phase margin at")
            self._pm.set_undefined(why)
            self._wc.set_undefined(why)

        if np.isfinite(data.gm_dB):
            self._gm.set_value(data.gm_dB, "{:.2f}")
        else:
            self._gm.set_undefined(
                "the phase never reaches −180°, so the gain margin is infinite")

    # ── for tests and callers ───────────────────────────────────

    @property
    def verdict(self) -> Status:
        return self._badge.status

    def summary(self) -> str:
        """The whole bar as one line — what a screen reader would announce."""
        return (f"{self._plant.text()}  {self._controller.text()}  "
                f"{self._badge.text()}  {self._note.text()}").strip()


def _divider() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.VLine)
    line.setFrameShadow(QFrame.Sunken)
    line.setContentsMargins(NORMAL, 0, NORMAL, 0)
    return line


def short_tf(tf: ctl.TransferFunction, limit: int = 46) -> str:
    """A factored transfer function, elided if it will not fit."""
    text = factored_str(tf)
    return text if len(text) <= limit else text[: limit - 1] + "…"

"""
The Modern tab: five state-space views over one shared model.
"""

from __future__ import annotations

import control as ctl
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QTabWidget,
                               QVBoxLayout, QWidget)

from ....core.architecture import CourseArchitecture
from ...guard import GuardedPanel, guard
from .context import ModernContext
from .discrete_view import DiscreteView
from .feedback_view import FeedbackView
from .observer_view import ObserverView
from .statespace_view import StateSpaceView
from .structure_view import StructureView


class ModernTab(QWidget, GuardedPanel):
    """
    State space, structure, feedback, observers and discrete time.

    All five views share one :class:`ModernContext`, so a model edited or
    reduced anywhere is the model every other view designs against. Without
    that, designing an observer for one realisation and a controller for
    another would silently produce a compensator that cannot be assembled.
    """

    #: The state-space model was pushed back to the classical half as G(s).
    model_sent_to_analysis = Signal()

    def __init__(self, arch: CourseArchitecture | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self._arch = arch
        self.ctx = ModernContext(self)
        self._build_ui()
        self.ctx.model_changed.connect(self._update_header)
        self.ctx.status.connect(self._status.setText)
        if arch is not None:
            self.load_from_plant()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(2)
        self.install_error_banner(root)

        header = QWidget()
        row = QHBoxLayout(header)
        row.setContentsMargins(6, 2, 6, 2)

        load = QPushButton("← Load plant G(s)")
        load.setToolTip(
            "Take the plant from the classical half as the state-space model "
            "to design against.")
        load.clicked.connect(self.load_from_plant)
        row.addWidget(load)

        send = QPushButton("Send to analysis →")
        send.setToolTip(
            "Push the current state-space model back to the classical tabs as "
            "G(s).")
        send.clicked.connect(self.send_to_analysis)
        row.addWidget(send)

        self._header = QLabel("")
        row.addWidget(self._header)
        row.addStretch()
        root.addWidget(header)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self.state_view = StateSpaceView(self.ctx)
        self.structure_view = StructureView(self.ctx)
        self.feedback_view = FeedbackView(self.ctx)
        self.observer_view = ObserverView(self.ctx)
        self.discrete_view = DiscreteView(self.ctx)
        for widget, title in (
            (self.state_view, "State Space"),
            (self.structure_view, "Structure"),
            (self.feedback_view, "State Feedback"),
            (self.observer_view, "Observer / Kalman"),
            (self.discrete_view, "Discrete"),
        ):
            self._tabs.addTab(widget, title)
        root.addWidget(self._tabs, stretch=1)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        self._update_header()

    # ── bridges to the classical half ───────────────────────────

    @guard("Load plant")
    def load_from_plant(self) -> None:
        if self._arch is None:
            self.ctx.status.emit("no plant available")
            return
        self.ctx.set_from_tf(self._arch.block_tf("G"), "plant G(s)")
        self.ctx.status.emit(
            "loaded G(s) as a state-space model in controllable canonical form")

    @guard("Send to analysis")
    def send_to_analysis(self) -> None:
        if self._arch is None:
            return
        self._arch.set_block("G", ctl.ss2tf(self.ctx.sys))
        self.ctx.status.emit(
            "sent to the classical tabs as G(s) — switch to System to see it")
        self.model_sent_to_analysis.emit()

    # ── housekeeping ────────────────────────────────────────────

    def _update_header(self) -> None:
        self._header.setText("   " + self.ctx.describe())

    def refresh(self, arch: CourseArchitecture | None = None) -> None:
        """Called when the tab is shown."""
        if arch is not None:
            self._arch = arch
        self._update_header()

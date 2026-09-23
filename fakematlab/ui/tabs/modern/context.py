"""
The state-space model the modern-control views share.

One object owns "the current model" and tells everyone when it changes, so the
five views never hold their own copy and cannot disagree about what is being
designed for. It also remembers the designs — ``K``, ``L`` — because the
Observer view needs the controller gain to demonstrate the separation
principle, and the Discrete view needs both.
"""

from __future__ import annotations

import control as ctl
import numpy as np
from PySide6.QtCore import QObject, Signal

from ....core.statespace import from_tf, state_space


class ModernContext(QObject):
    """Shared state for the modern-control views."""

    #: The state-space model changed (edited, or loaded from the plant).
    model_changed = Signal()
    #: A state-feedback gain was designed.
    feedback_changed = Signal(object)          # K or None
    #: An observer gain was designed.
    observer_changed = Signal(object)          # L or None
    #: Human-readable note for the status line.
    status = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # A stable, controllable, observable default: something every view can
        # show immediately rather than starting on an empty or degenerate model.
        self._sys = state_space([[0.0, 1.0], [-2.0, -3.0]],
                                [[0.0], [1.0]], [[1.0, 0.0]])
        self._source = "default 2nd-order plant"
        self._K: np.ndarray | None = None
        self._L: np.ndarray | None = None

    # ── the model ───────────────────────────────────────────────

    @property
    def sys(self) -> ctl.StateSpace:
        return self._sys

    @property
    def source(self) -> str:
        """Where the current model came from — shown so it is never a mystery."""
        return self._source

    def set_system(self, sys: ctl.StateSpace, source: str = "edited") -> None:
        self._sys = sys
        self._source = source
        # A gain designed for the previous model has the wrong shape, and
        # silently keeping it would produce a design that looks valid and is
        # not. Clearing is the honest response to the model changing.
        self.set_feedback(None)
        self.set_observer(None)
        self.model_changed.emit()

    def set_from_tf(self, tf: ctl.TransferFunction,
                    source: str = "plant G(s)") -> None:
        self.set_system(from_tf(tf), source)

    # ── designs ─────────────────────────────────────────────────

    @property
    def K(self) -> np.ndarray | None:
        return self._K

    @property
    def L(self) -> np.ndarray | None:
        return self._L

    def set_feedback(self, K) -> None:
        self._K = None if K is None else np.atleast_2d(np.asarray(K, float))
        self.feedback_changed.emit(self._K)

    def set_observer(self, L) -> None:
        self._L = None if L is None else np.atleast_2d(np.asarray(L, float))
        self.observer_changed.emit(self._L)

    # ── convenience ─────────────────────────────────────────────

    @property
    def n(self) -> int:
        return int(self._sys.nstates)

    def describe(self) -> str:
        return (f"{self.n} states · from {self._source}"
                + (f" · K set" if self._K is not None else "")
                + (f" · L set" if self._L is not None else ""))

"""
The course's chosen architecture (ch.5, slide 16/24) — as a Model preset.
========================================================================

         di                do
          │                 │
 r ──[K₁]──⊕──e──[K₂]──u────⊕──[G]────⊕──── y
           │(−)                         │   │
           └────────[H]────⊕────────────┘   │
                           │(+n)            │
                           └────────────────┘

Signals
    r   reference            y   plant output
    di  input disturbance    u   plant input  (K₂ output + di)
    do  output disturbance   e   error        (K₁·r − H·y_meas)
    n   measurement noise

Blocks: ``K₁`` feedforward, ``K₂`` feedback controller, ``G`` plant, ``H`` sensor.

How this differs from v1
------------------------
v1 hard-coded the twelve closed-loop transfer functions as algebraic
expressions.  Six of them were wrong, and every one of them silently assumed
``H = 1`` — so the editable ``H`` block on the canvas was a trap.

Here the diagram is a :class:`~fakematlab.core.model.Model` and every transfer
function is derived from it on demand by :mod:`fakematlab.core.algebra`.  The
drawn topology *is* the mathematics, so the two cannot drift apart.  This class
is now a thin convenience wrapper with the course's vocabulary (L, S, T, K₁,
K₂) over that model.
"""

from __future__ import annotations

from dataclasses import dataclass

import control as ctl
import numpy as np

from . import algebra as _alg
from .internal import InternalStabilityReport, internal_stability
from .model import Model
from .tf_utils import SystemInfo, analyse, unity

# Signals available as analysis taps
INPUT_SIGNALS = ("r", "di", "do", "n")
OUTPUT_SIGNALS = ("y", "u", "e")
ALL_SIGNALS = INPUT_SIGNALS + OUTPUT_SIGNALS

#: The four editable blocks, in the order the UI presents them.
BLOCK_IDS = ("K1", "K2", "G", "H")

_BLOCK_LABELS = {
    "K1": ("K₁(s)", "Feedforward controller"),
    "K2": ("K₂(s)", "Feedback controller"),
    "G":  ("G(s)",  "Plant"),
    "H":  ("H(s)",  "Sensor"),
}


@dataclass
class BlockDef:
    """One editable block. Kept for the block editor's benefit."""
    block_id: str
    label: str
    tf: ctl.TransferFunction
    description: str = ""


# ──────────────────────────────────────────────────────────────
#  Model construction
# ──────────────────────────────────────────────────────────────

def build_course_model(
    G:  ctl.TransferFunction | None = None,
    K2: ctl.TransferFunction | None = None,
    K1: ctl.TransferFunction | None = None,
    H:  ctl.TransferFunction | None = None,
) -> Model:
    """
    Build the ch.5 2-DOF architecture as a generic :class:`Model`.

    Every sign lives on an edge, matching the drawn diagram exactly:
    the feedback path into ``sum_e`` carries ``gain=-1``; noise is *added*
    into the measurement, as slide 17/24 draws it.
    """
    m = Model("course 2-DOF (ch.5 slide 16/24)")

    for sig in INPUT_SIGNALS:
        m.add_wire(sig, label=sig)
        m.add_input(sig)

    m.add_block("K1", K1 or unity(), label="K₁(s)")
    m.add_block("K2", K2 or unity(), label="K₂(s)")
    m.add_block("G",  G  or ctl.TransferFunction([1], [1, 1]), label="G(s)")
    m.add_block("H",  H  or unity(), label="H(s)")

    m.add_sum("sum_e", label="⊕")     # K₁·r − H·y_meas
    m.add_sum("sum_y", label="⊕")     # G·u + do
    m.add_sum("sum_m", label="⊕")     # y + n  → sensor input

    m.add_wire("e", label="e")
    m.add_wire("u", label="u")        # plant input: K₂ output + di
    m.add_wire("y", label="y")
    for sig in OUTPUT_SIGNALS:
        m.add_output(sig)

    (m.connect("r", "K1")
      .connect("K1", "sum_e")
      .connect("H", "sum_e", gain=-1)       # negative feedback
      .connect("sum_e", "e")
      .connect("e", "K2")
      .connect("K2", "u")
      .connect("di", "u")                   # input disturbance at plant input
      .connect("u", "G")
      .connect("G", "sum_y")
      .connect("do", "sum_y")               # output disturbance
      .connect("sum_y", "y")
      .connect("y", "sum_m")
      .connect("n", "sum_m")                # noise added into the measurement
      .connect("sum_m", "H"))
    return m


# ──────────────────────────────────────────────────────────────
#  Architecture
# ──────────────────────────────────────────────────────────────

class CourseArchitecture:
    """
    The ch.5 2-DOF feedback + feedforward architecture.

    A convenience façade over a :class:`Model`: it names the four blocks and
    the course's derived quantities (L, S, T), but performs no algebra of its
    own.  Reach for :attr:`model` whenever you want the general object.
    """

    def __init__(
        self,
        G:  ctl.TransferFunction | None = None,
        K2: ctl.TransferFunction | None = None,
        K1: ctl.TransferFunction | None = None,
        H:  ctl.TransferFunction | None = None,
    ) -> None:
        self._model = build_course_model(G=G, K2=K2, K1=K1, H=H)

    # ── the underlying model ────────────────────────────────────

    @property
    def model(self) -> Model:
        """The generic graph. Everything else here is sugar over it."""
        return self._model

    # ── block management ────────────────────────────────────────

    def set_block(self, block_id: str, tf: ctl.TransferFunction) -> None:
        if block_id not in BLOCK_IDS:
            raise KeyError(f"Unknown block {block_id!r}. Valid: {list(BLOCK_IDS)}")
        self._model.set_tf(block_id, tf)

    def get_block(self, block_id: str) -> BlockDef:
        label, desc = _BLOCK_LABELS[block_id]
        return BlockDef(block_id, label, self._model.tf(block_id), desc)

    def block_tf(self, block_id: str) -> ctl.TransferFunction:
        return self._model.tf(block_id)

    def blocks(self) -> list[BlockDef]:
        return [self.get_block(b) for b in BLOCK_IDS]

    # ── derived transfer functions ──────────────────────────────

    def loop_tf(self) -> ctl.TransferFunction:
        """
        ``L(s)`` — the loop transfer function, obtained by breaking the loop
        at the error node. Equals ``K₂·G·H`` for this topology, but is derived
        from the graph rather than assumed.
        """
        return _alg.loop_transfer_function(self._model, "e")

    def sensitivity(self) -> ctl.TransferFunction:
        """``S(s) = 1/(1+L)`` — how output disturbance reaches the output."""
        return ctl.feedback(unity(), self.loop_tf())

    def compl_sensitivity(self) -> ctl.TransferFunction:
        """``T(s) = L/(1+L) = 1 − S``."""
        return ctl.feedback(self.loop_tf(), unity())

    def get_closed_loop_tf(self, input_sig: str,
                           output_sig: str) -> ctl.TransferFunction:
        """
        Exact closed-loop TF for any (input, output) pair.

        Derived from the graph, so it is correct for ``K₁ ≠ 1`` and ``H ≠ 1``
        — the cases v1 got wrong.
        """
        if input_sig not in INPUT_SIGNALS:
            raise ValueError(f"Unknown input {input_sig!r}. "
                             f"Valid: {list(INPUT_SIGNALS)}")
        if output_sig not in OUTPUT_SIGNALS:
            raise ValueError(f"Unknown output {output_sig!r}. "
                             f"Valid: {list(OUTPUT_SIGNALS)}")
        return _alg.transfer_function(self._model, input_sig, output_sig)

    def all_closed_loop_tfs(self) -> dict[tuple[str, str], ctl.TransferFunction]:
        """All twelve (input, output) transfer functions."""
        out: dict[tuple[str, str], ctl.TransferFunction] = {}
        for i in INPUT_SIGNALS:
            mat = _alg.transfer_matrix(self._model, i)
            for o in OUTPUT_SIGNALS:
                out[(i, o)] = mat[o]
        return out

    def open_loop_tf(self) -> ctl.TransferFunction:
        """``G(s)`` — the plant alone."""
        return self.block_tf("G")

    # ── stability ───────────────────────────────────────────────

    def characteristic_polynomial(self) -> np.ndarray:
        """Coefficients of the interconnection's characteristic polynomial."""
        return _alg.characteristic_polynomial(self._model)

    def closed_loop_poles(self) -> np.ndarray:
        """Every closed-loop mode, hidden ones included."""
        return _alg.closed_loop_poles(self._model)

    def internal_stability(self) -> InternalStabilityReport:
        """
        Ch.6 internal stability: are *all* loop transfer functions stable?

        See :mod:`fakematlab.core.internal` — this catches unstable pole/zero
        cancellations that every individual step response would hide.
        """
        return internal_stability(self._model)

    # ── analysis shortcuts ──────────────────────────────────────

    def analyse_plant(self) -> SystemInfo:
        return analyse(self.block_tf("G"))

    def analyse_loop(self) -> SystemInfo:
        return analyse(self.loop_tf())

    def analyse_closed_loop(self, input_sig: str = "r",
                            output_sig: str = "y") -> SystemInfo:
        return analyse(self.get_closed_loop_tf(input_sig, output_sig))

    # ── repr ────────────────────────────────────────────────────

    def __repr__(self) -> str:
        lines = ["CourseArchitecture:"]
        for bid in BLOCK_IDS:
            lines.append(f"  {bid}: {self.block_tf(bid)}")
        return "\n".join(lines)

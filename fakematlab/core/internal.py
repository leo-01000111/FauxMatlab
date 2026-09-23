"""
Internal (nominal) stability — ch.6, slide 1/26.
================================================
    "The closed-loop is internally stable if **all** the transfer functions
     of the loop are stable."

Checking one transfer function is not enough, and the gap is not academic.
Take ``G = 1/(s−1)`` with ``K₂ = (s−1)/(s+2)``.  The unstable plant pole is
cancelled by the controller zero, so::

    r → y  =  1/(s+3)          ← looks perfectly stable

…while the mode at ``s = +1`` is still there, unobservable from ``r`` and
growing.  v1 reported "✓ Stable" for exactly this case.

This module answers the question properly, from the interconnection's own
characteristic polynomial ``det(M')`` (see :mod:`fakematlab.core.algebra`),
which retains every mode *including* the ones that cancel out of the
individual transfer functions.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import control as ctl
import numpy as np

from . import algebra as _alg
from .model import Model


@dataclass
class Cancellation:
    """A zero of one block sitting on a pole of another."""
    location:   complex
    zero_of:    str
    pole_of:    str
    unstable:   bool     # Re ≥ 0 → the cancellation hides a divergent mode
    distance:   float    # how close they actually are

    def describe(self) -> str:
        where = _fmt(self.location)
        kind = "UNSTABLE" if self.unstable else "stable"
        return (f"{kind} pole/zero cancellation at s = {where}: "
                f"zero of {self.zero_of} against pole of {self.pole_of}")


@dataclass
class InternalStabilityReport:
    """Verdict on the whole interconnection, not on one transfer function."""
    stable:          bool
    modes:           np.ndarray            # every root of det(M')
    unstable_modes:  list[complex]
    hidden_modes:    list[complex]         # invisible from every declared port
    unstable_hidden: list[complex]         # invisible *and* divergent
    cancellations:   list[Cancellation]
    io_stability:    dict[tuple[str, str], bool] = field(default_factory=dict)
    reference:       str | None = None     # the input treated as "the reference"
    note:            str = ""

    @property
    def unstable_pairs(self) -> list[tuple[str, str]]:
        """The (input, output) pairs whose transfer function is unstable."""
        return [pair for pair, ok in self.io_stability.items() if not ok]

    @property
    def reference_path_stable(self) -> bool:
        """
        True when every transfer function *from the reference* is stable.

        This is what a step response shows, and it is all most people look at.
        """
        ref = self.reference
        pairs = [ok for (i, _o), ok in self.io_stability.items() if i == ref]
        return all(pairs) if pairs else False

    @property
    def deceptive(self) -> bool:
        """
        True when the reference response looks perfectly healthy and the loop
        is nevertheless unstable.

        This is the case worth shouting about, and the reason ch.6 defines
        stability over *all* the loop transfer functions rather than the
        obvious one: the step response settles, the Bode plot looks textbook,
        and a disturbance still makes the hardware run away.
        """
        return not self.stable and self.reference_path_stable

    def verdict(self) -> str:
        if self.stable:
            return "✓ Internally stable — all closed-loop modes in the open LHP"
        modes = ", ".join(_fmt(m) for m in self.unstable_modes)
        if self.deceptive:
            exposed = ", ".join(f"{i}→{o}" for i, o in self.unstable_pairs)
            detail = (f"only {exposed} expose{'s' if len(self.unstable_pairs) == 1 else ''} it"
                      if exposed else "no transfer function exposes it")
            return (f"✗ NOT internally stable — unstable mode(s) at {modes}, "
                    f"but every response from {self.reference!r} looks stable; "
                    f"{detail}.")
        return f"✗ NOT internally stable — unstable mode(s) at {modes}"

    def summary(self) -> str:
        lines = [self.verdict()]
        if self.unstable_pairs:
            lines.append("Unstable transfer functions: "
                         + ", ".join(f"{i}→{o}" for i, o in self.unstable_pairs))
        if self.hidden_modes:
            lines.append("Hidden modes (not visible from any port): "
                         + ", ".join(_fmt(m) for m in self.hidden_modes))
        for c in self.cancellations:
            lines.append(c.describe())
        if self.note:
            lines.append(self.note)
        return "\n".join(lines)


# ──────────────────────────────────────────────────────────────
#  Analysis
# ──────────────────────────────────────────────────────────────

def internal_stability(model: Model, tol: float = 1e-6,
                       reference: str | None = None) -> InternalStabilityReport:
    """
    Full internal-stability analysis of a model.

    ``tol`` is the relative tolerance used to decide whether two roots are the
    same root — it controls both hidden-mode matching and pole/zero
    cancellation detection.

    ``reference`` names the input a user would normally plot against (the
    first declared input by default). It is used only to decide whether a
    failure is *deceptive* — invisible from the responses anyone actually
    looks at.
    """
    if reference is None:
        reference = model.inputs[0] if model.inputs else None
    modes = _alg.closed_loop_poles(model)
    unstable = [complex(m) for m in modes if m.real >= -_abs_tol(m, tol)]

    # Which modes survive into at least one declared input→output path?
    visible: list[complex] = []
    io_stability: dict[tuple[str, str], bool] = {}
    for in_id in model.inputs:
        try:
            mat = _alg.transfer_matrix(model, in_id)
        except Exception:                      # ill-posed → caller sees it via modes
            continue
        for out_id in model.outputs:
            tf = mat.get(out_id)
            if tf is None:
                continue
            poles = np.atleast_1d(ctl.poles(tf))
            io_stability[(in_id, out_id)] = bool(
                all(p.real < -_abs_tol(p, tol) for p in poles)
            ) if len(poles) else True
            visible.extend(complex(p) for p in poles)

    hidden = [complex(m) for m in modes if not _matches_any(m, visible, tol)]
    unstable_hidden = [m for m in hidden if m.real >= -_abs_tol(m, tol)]

    report = InternalStabilityReport(
        stable=len(unstable) == 0,
        modes=modes,
        unstable_modes=unstable,
        hidden_modes=hidden,
        unstable_hidden=unstable_hidden,
        cancellations=find_cancellations(model, tol),
        io_stability=io_stability,
        reference=reference,
    )
    if report.deceptive:
        unstable_cancel = [c for c in report.cancellations if c.unstable]
        cause = ""
        if unstable_cancel:
            c = unstable_cancel[0]
            cause = (f" The zero of {c.zero_of} cancels the unstable pole of "
                     f"{c.pole_of} at s = {_fmt(c.location)}, which removes the "
                     f"mode from the reference response without removing it "
                     f"from the system.")
        report.note = (
            "Do not trust the step response here: it is computed from a "
            "transfer function the unstable mode has cancelled out of."
            + cause +
            " A disturbance excites it and the output diverges (ch.6, 1/26)."
        )
    return report


def find_cancellations(model: Model, tol: float = 1e-6) -> list[Cancellation]:
    """
    Zeros of one block sitting on poles of another.

    Only cross-block pairs are reported: a block that cancels its *own* pole
    with its *own* zero was entered that way deliberately and is not a
    property of the interconnection.
    """
    zeros: list[tuple[str, complex]] = []
    poles: list[tuple[str, complex]] = []
    for node in model.blocks():
        for z in np.atleast_1d(ctl.zeros(node.tf)):
            zeros.append((node.node_id, complex(z)))
        for p in np.atleast_1d(ctl.poles(node.tf)):
            poles.append((node.node_id, complex(p)))

    found: list[Cancellation] = []
    for z_owner, z in zeros:
        for p_owner, p in poles:
            if z_owner == p_owner:
                continue
            d = abs(z - p)
            if d <= _abs_tol(p, tol):
                found.append(Cancellation(
                    location=p,
                    zero_of=z_owner,
                    pole_of=p_owner,
                    unstable=p.real >= -_abs_tol(p, tol),
                    distance=float(d),
                ))
    # Unstable ones first — those are the ones a user must see.
    found.sort(key=lambda c: (not c.unstable, -c.location.real))
    return found


# ──────────────────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────────────────

def _abs_tol(value: complex, rel: float) -> float:
    """Absolute tolerance scaled to the magnitude of the root."""
    return rel * max(1.0, abs(value))


def _matches_any(value: complex, pool: list[complex], tol: float) -> bool:
    return any(abs(value - other) <= _abs_tol(value, tol) for other in pool)


def _fmt(z: complex) -> str:
    if abs(z.imag) < 1e-10:
        return f"{z.real:.4g}"
    sign = "+" if z.imag >= 0 else "−"
    return f"{z.real:.4g} {sign} {abs(z.imag):.4g}j"

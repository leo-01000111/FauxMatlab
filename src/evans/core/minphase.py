"""
Minimum-phase / all-pass factorisation (ch.4, slides 44 and 46).
================================================================
A transfer function with zeros in the right half-plane is *non-minimum
phase*: it lags more than a system with the same magnitude curve and all its
zeros on the left. The course's trick is to dissolve it into two systems.

Write ``G(s) = n(s)/d(s)`` and split the numerator into the factor ``ñ⁺(s)``
holding the RHP zeros and ``n⁻(s)`` holding the rest. Let ``ñ⁻(s)`` be the
*mirror* of ``ñ⁺`` (each zero reflected across the imaginary axis into the
LHP). Multiplying and dividing by it gives::

    G(s) = [ ñ⁺(s) / ñ⁻(s) ] · [ ñ⁻(s) n⁻(s) / d(s) ] = G_ap(s) · G_mp(s)

* ``|G_ap(jω)| = 1`` for every ω, because ``ñ⁺(jω)`` and ``ñ⁻(jω)`` are
  complex conjugates up to a sign — the factor only *delays* phase.
* Hence ``|G| = |G_mp|`` everywhere: the magnitude curve is untouched and all
  the extra phase lag sits in ``G_ap``.
* ``G_mp`` has every zero in the closed LHP, i.e. it is minimum phase.

Conventions
-----------
* ``G_ap`` is exactly the slide's ``ñ⁺/ñ⁻`` with both factors monic, so a
  zero at ``s = 3`` gives ``(s−3)/(s+3)``, not ``(3−s)/(3+s)``. With ``m``
  RHP zeros that makes ``G_ap(0) = (−1)ᵐ``: the all-pass starts at 180° when
  ``m`` is odd. The course writes it this way, so this does too, and the
  gain of ``G`` stays in ``G_mp`` untouched.
* Zeros *on* the imaginary axis (including the origin) are not in the open
  RHP, so they stay in ``G_mp``. They are not "non-minimum phase" in the
  strict sense, though they do make the phase jump, and the explanation says so.
* RHP *poles* are not touched: they make the plant unstable, which is a
  different problem from non-minimum phase, and no all-pass factor fixes it.

Only continuous-time SISO rational systems are handled; a delay must already
be a Padé rational (which is itself an all-pass, and is dissolved as one).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import control as ctl
import numpy as np

from .tf_utils import _clean_roots

#: Relative distance from the imaginary axis below which a zero counts as on it.
AXIS_TOL = 1e-6


@dataclass
class MinPhaseSplit:
    """Result of :func:`minimum_phase_split`."""
    allpass: ctl.TransferFunction          # G_ap = ñ⁺/ñ⁻, both monic
    minphase: ctl.TransferFunction         # G_mp = G / G_ap
    rhp_zeros: list[complex]               # zeros with Re > 0
    mirrored_zeros: list[complex]          # their reflections, −z
    is_minimum_phase: bool                 # no zero in the open RHP
    imag_axis_zeros: list[complex] = field(default_factory=list)
    rhp_poles: list[complex] = field(default_factory=list)
    explanation: str = ""

    def __iter__(self):
        """``Gap, Gmp = split`` — the MATLAB-style two-output unpacking."""
        yield self.allpass
        yield self.minphase


def minimum_phase_split(G) -> MinPhaseSplit:
    """
    Dissolve ``G`` into ``G_allpass · G_mp`` (see the module docstring).

    Raises ``ValueError`` for MIMO or discrete-time systems.
    """
    if not isinstance(G, ctl.TransferFunction):
        try:
            G = ctl.ss2tf(G)
        except Exception as exc:                                  # noqa: BLE001
            raise ValueError(f"expected a transfer function, got "
                             f"{type(G).__name__}") from exc
    if G.ninputs != 1 or G.noutputs != 1:
        raise ValueError("minimum-phase split needs a SISO transfer function "
                         f"(got {G.noutputs}x{G.ninputs})")
    if G.dt:
        raise ValueError("minimum-phase split is defined for continuous-time "
                         "systems (discrete: the unit circle, not the "
                         "imaginary axis, is the boundary)")

    num = np.trim_zeros(np.atleast_1d(np.asarray(G.num[0][0], float)), "f")
    den = np.trim_zeros(np.atleast_1d(np.asarray(G.den[0][0], float)), "f")
    if num.size == 0:                                   # G identically 0
        one = ctl.TransferFunction([1.0], [1.0])
        return MinPhaseSplit(one, G, [], [], True, explanation=(
            "G is identically zero: nothing to split (all-pass = 1)."))
    k = float(num[0])
    zeros = _clean_roots(np.roots(num)) if num.size > 1 else []
    poles = np.atleast_1d(np.roots(den)) if den.size > 1 else np.array([])

    rhp, axis, lhp = [], [], []
    for z in zeros:
        scale = max(1.0, abs(z))
        if abs(z.real) <= AXIS_TOL * scale:
            axis.append(complex(0.0, z.imag))           # snap onto the axis
        elif z.real > 0:
            rhp.append(z)
        else:
            lhp.append(z)
    mirrored = [-z for z in rhp]
    m = len(rhp)

    n_plus = _real_poly(rhp)                            # ñ⁺ = Π(s − z)
    n_minus = _real_poly(mirrored)                      # ñ⁻ = Π(s + z)
    rest = _real_poly(lhp + axis)                       # n⁻, monic

    allpass = ctl.TransferFunction(n_plus, n_minus)
    mp_num = k * np.convolve(n_minus, rest)
    minphase = ctl.TransferFunction(mp_num, den)

    rhp_poles = [complex(p) for p in poles if p.real > AXIS_TOL]
    return MinPhaseSplit(
        allpass=allpass, minphase=minphase,
        rhp_zeros=[complex(z) for z in rhp],
        mirrored_zeros=[complex(z) for z in mirrored],
        is_minimum_phase=(m == 0),
        imag_axis_zeros=[complex(z) for z in axis],
        rhp_poles=rhp_poles,
        explanation=_explain(rhp, mirrored, axis, rhp_poles),
    )


def _real_poly(roots) -> np.ndarray:
    """Monic real polynomial with the given roots (conjugates come in pairs)."""
    if len(roots) == 0:
        return np.array([1.0])
    return np.real(np.poly(np.asarray(roots, dtype=complex)))


def _fmt(z: complex) -> str:
    if abs(z.imag) < 1e-9 * max(1.0, abs(z)):
        return f"{z.real:.4g}"
    return f"{z.real:.4g}{'+' if z.imag >= 0 else '-'}{abs(z.imag):.4g}j"


def _explain(rhp, mirrored, axis, rhp_poles) -> str:
    lines = []
    if not rhp:
        lines.append("Already minimum phase: no zero in the open right "
                     "half-plane, so G_allpass = 1 and G_mp = G.")
    else:
        lines.append(
            f"{len(rhp)} RHP zero(s) at " + ", ".join(_fmt(z) for z in rhp)
            + " are mirrored to " + ", ".join(_fmt(z) for z in mirrored)
            + ". G_allpass = ñ⁺/ñ⁻ has |G_allpass(jω)| = 1, so |G| = |G_mp|; "
              "the extra phase lag of G is all in G_allpass.")
    if axis:
        lines.append(
            "Zero(s) on the imaginary axis (" + ", ".join(_fmt(z) for z in axis)
            + ") are not in the open RHP and stay in G_mp.")
    if rhp_poles:
        lines.append(
            "Note: " + str(len(rhp_poles)) + " RHP pole(s) ("
            + ", ".join(_fmt(p) for p in rhp_poles) + ") are not touched by "
            "this split — they make G unstable, which is a separate problem.")
    return " ".join(lines)

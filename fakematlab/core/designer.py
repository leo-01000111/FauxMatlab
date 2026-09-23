"""
The Control System Designer's arithmetic — sisotool, minus the drawing.
=======================================================================

The gesture MATLAB's ``sisotool`` is built around: grab a closed-loop pole on
the root locus, drag it, and watch the Bode plot and the step response follow.
Everything the app needs to answer "what gain puts a pole *here*?" lives in
this module, so the question can be asked — and checked — without a window.

**Where the gain comes from.** A point ``s`` is on the locus when
``∠L(s) = 180°``; the gain there is then fixed by the magnitude condition
``K = 1/|L(s)|``. A dragged point is almost never exactly on the locus, so
:func:`point_to_gain` does what the app does visually: it finds the nearest
sampled locus point, then refines the gain by minimising the distance along
that branch. The alternative — applying ``K = 1/|L(s)|`` to the raw dragged
point — silently answers a different question, because off the locus that
gain places the pole somewhere else entirely.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import control as ctl
import numpy as np
from scipy.optimize import minimize_scalar

from .freqresp import bode
from .stability import RootLocusData, root_locus
from .tf_utils import from_zpk
from .timeresp import StepMetrics, compute_step_metrics, step_response


# ──────────────────────────────────────────────────────────────
#  The compensator being designed
# ──────────────────────────────────────────────────────────────

@dataclass
class Compensator:
    """
    ``C(s) = K · Π(s − zᵢ) / Π(s − pⱼ)`` — the thing the designer edits.

    Zeros and poles are stored as a flat list of complex numbers. A complex
    pair must be given as both members; :meth:`add_pair` does that, and
    :meth:`is_real_coefficient` says whether the current lists produce a
    physically realisable compensator.
    """

    gain: float = 1.0
    zeros: list[complex] = field(default_factory=list)
    poles: list[complex] = field(default_factory=list)

    def tf(self) -> ctl.TransferFunction:
        return from_zpk(list(self.zeros), list(self.poles), float(self.gain))

    def add_pair(self, where: complex, as_zero: bool) -> None:
        """Add a complex-conjugate pair (or a single root if it is real)."""
        target = self.zeros if as_zero else self.poles
        if abs(where.imag) < 1e-12:
            target.append(complex(where.real, 0.0))
        else:
            target.append(where)
            target.append(np.conj(where))

    def is_real_coefficient(self, tol: float = 1e-9) -> bool:
        """Whether every complex root is matched by its conjugate."""
        for roots in (self.zeros, self.poles):
            remaining = list(roots)
            for root in roots:
                if abs(root.imag) < tol:
                    continue
                if not any(abs(other - np.conj(root)) < tol
                           for other in remaining):
                    return False
        return True

    @property
    def is_proper(self) -> bool:
        return len(self.zeros) <= len(self.poles) or not self.poles

    def describe(self) -> str:
        parts = [f"K = {self.gain:.5g}"]
        if self.zeros:
            parts.append("zeros: " + ", ".join(_fmt(z) for z in self.zeros))
        if self.poles:
            parts.append("poles: " + ", ".join(_fmt(p) for p in self.poles))
        return "   ".join(parts)

    def copy(self) -> "Compensator":
        return Compensator(self.gain, list(self.zeros), list(self.poles))


def _fmt(root: complex) -> str:
    if abs(root.imag) < 1e-12:
        return f"{root.real:.4g}"
    return f"{root.real:.4g}{root.imag:+.4g}j"


# ──────────────────────────────────────────────────────────────
#  Picking a gain off the locus
# ──────────────────────────────────────────────────────────────

@dataclass
class DesignPoint:
    """The result of asking "what gain puts a closed-loop pole here?"."""

    K: float
    pole: complex              # the closed-loop pole nearest the request
    poles: np.ndarray          # every closed-loop pole at this gain
    zeta: float                # damping ratio of `pole`
    wn: float                  # natural frequency of `pole`, rad/s
    distance: float            # |pole − requested point|
    on_locus: bool             # whether the request was essentially on it

    def describe(self) -> str:
        return (f"K = {self.K:.5g}   pole = {_fmt(self.pole)}   "
                f"ζ = {self.zeta:.3f}   ωn = {self.wn:.4g} rad/s")


def point_to_gain(L: ctl.TransferFunction, point: complex,
                  locus: RootLocusData | None = None,
                  K_max: float | None = None) -> DesignPoint:
    """
    The gain whose closed-loop poles come nearest ``point``.

    Uses a sampled locus for the coarse search and a bounded scalar
    minimisation for the refinement, so the answer is not limited to the
    sample spacing — dragging a pole is continuous, and a result that snapped
    to 400 discrete gains would feel, and be, wrong.
    """
    if locus is None:
        locus = root_locus(L, K_max=K_max)
    K_values, roots = locus.K_values, locus.roots

    distances = np.abs(roots - point)
    distances = np.where(np.isnan(distances), np.inf, distances)
    i, _ = np.unravel_index(int(np.argmin(distances)), distances.shape)

    lo = float(K_values[max(i - 1, 0)])
    hi = float(K_values[min(i + 1, len(K_values) - 1)])
    K = float(K_values[i])
    if hi > lo:
        result = minimize_scalar(
            lambda k: _closest_distance(L, k, point),
            bounds=(lo, hi), method="bounded",
            options={"xatol": (hi - lo) * 1e-6},
        )
        if result.success and result.fun <= _closest_distance(L, K, point):
            K = float(result.x)

    poles = closed_loop_poles(L, K)
    nearest = min(poles, key=lambda p: abs(p - point))
    distance = float(abs(nearest - point))
    zeta, wn = damping_of(nearest)
    return DesignPoint(
        K=max(K, 0.0), pole=complex(nearest), poles=poles,
        zeta=zeta, wn=wn, distance=distance,
        on_locus=distance <= 0.02 * max(abs(point), 1.0),
    )


def closed_loop_poles(L: ctl.TransferFunction, K: float) -> np.ndarray:
    """Roots of ``den(s) + K·num(s)`` — the poles of ``K·L/(1+K·L)``."""
    num = np.atleast_1d(L.num[0][0])
    den = np.atleast_1d(L.den[0][0])
    width = max(len(num), len(den))
    num = np.pad(num, (width - len(num), 0))
    den = np.pad(den, (width - len(den), 0))
    return np.roots(den + K * num)


def _closest_distance(L: ctl.TransferFunction, K: float,
                      point: complex) -> float:
    poles = closed_loop_poles(L, max(float(K), 0.0))
    if not len(poles):
        return float("inf")
    return float(np.min(np.abs(poles - point)))


def damping_of(pole: complex) -> tuple[float, float]:
    """``(ζ, ωn)`` of one pole. A pole on the real axis has ζ = 1."""
    wn = float(abs(pole))
    if wn < 1e-15:
        return 0.0, 0.0
    return float(-pole.real / wn), wn


def gain_for_damping(L: ctl.TransferFunction, zeta: float,
                     locus: RootLocusData | None = None) -> DesignPoint | None:
    """
    The smallest gain putting the *dominant* closed-loop pair at damping
    ``zeta`` — the ch.8 exercise, "find K for ζ = 0.5".

    Returns ``None`` when no gain on the locus achieves it, which is a real
    answer: an overdamped locus that never leaves the real axis has no ζ < 1
    to find.
    """
    if not 0.0 < zeta < 1.0:
        raise ValueError(f"damping must lie in (0, 1), got {zeta}")
    if locus is None:
        locus = root_locus(L)

    previous_K = float(locus.K_values[0])
    previous_z = _dominant_damping(L, previous_K)
    for K in locus.K_values[1:]:
        K = float(K)
        z = _dominant_damping(L, K)
        crosses = (np.isfinite(z) and np.isfinite(previous_z)
                   and (previous_z - zeta) * (z - zeta) <= 0)
        if crosses:
            K_exact = _bisect_damping(L, zeta, previous_K, K)
            poles = closed_loop_poles(L, K_exact)
            pole = _dominant_pole(poles)
            z_exact, wn = damping_of(pole)
            return DesignPoint(K=K_exact, pole=pole, poles=poles,
                               zeta=z_exact, wn=wn, distance=0.0,
                               on_locus=True)
        previous_K, previous_z = K, z
    return None


def gain_for_overshoot(L: ctl.TransferFunction,
                       overshoot_pct: float) -> DesignPoint | None:
    """
    The gain giving a target overshoot, via the second-order relation
    ``ζ = −ln(Mp) / √(π² + ln²Mp)``.

    That relation is exact only for a pure second-order system with no zeros,
    so the achieved overshoot of a higher-order loop will differ — which is
    why the designer reports the *simulated* overshoot alongside.
    """
    Mp = float(overshoot_pct) / 100.0
    if not 0.0 < Mp < 1.0:
        raise ValueError(f"overshoot must lie in (0, 100)%, got {overshoot_pct}")
    ln = np.log(Mp)
    zeta = float(-ln / np.sqrt(np.pi ** 2 + ln ** 2))
    return gain_for_damping(L, zeta)


def _dominant_pole(poles: np.ndarray) -> complex:
    """The pole nearest the imaginary axis — the slowest mode."""
    stable = [p for p in poles if p.real < 0]
    candidates = stable or list(poles)
    return complex(max(candidates, key=lambda p: p.real))


def _dominant_damping(L: ctl.TransferFunction, K: float) -> float:
    poles = closed_loop_poles(L, K)
    if not len(poles):
        return float("nan")
    return damping_of(_dominant_pole(poles))[0]


def _bisect_damping(L: ctl.TransferFunction, target: float,
                    K_lo: float, K_hi: float, iterations: int = 60) -> float:
    f_lo = _dominant_damping(L, K_lo) - target
    for _ in range(iterations):
        K_mid = 0.5 * (K_lo + K_hi)
        f_mid = _dominant_damping(L, K_mid) - target
        if not np.isfinite(f_mid):
            break
        if (f_lo < 0) == (f_mid < 0):
            K_lo, f_lo = K_mid, f_mid
        else:
            K_hi = K_mid
    return float(0.5 * (K_lo + K_hi))


# ──────────────────────────────────────────────────────────────
#  The whole design, in one object
# ──────────────────────────────────────────────────────────────

@dataclass
class DesignSummary:
    """Everything the three linked plots and the readout need."""

    compensator: Compensator
    L: ctl.TransferFunction              # compensated open loop C·G·H
    T: ctl.TransferFunction              # closed loop
    locus: RootLocusData
    closed_loop_poles: np.ndarray
    gm_dB: float
    pm_deg: float
    wc: float
    w180: float
    stable: bool
    metrics: StepMetrics | None
    note: str = ""

    def describe(self) -> str:
        lines = [self.compensator.describe()]
        lines.append(
            f"GM = {self.gm_dB:.2f} dB    PM = {self.pm_deg:.1f}°    "
            f"ωc = {self.wc:.4g} rad/s")
        lines.append("closed loop: " + ("stable" if self.stable
                                        else "UNSTABLE"))
        if self.metrics is not None:
            lines.append(
                f"overshoot {self.metrics.Mp_pct:.1f}%    "
                f"ts(±2%) {self.metrics.ts_2pct:.3g} s    "
                f"y∞ {self.metrics.y_inf:.4g}")
        if self.note:
            lines.append(self.note)
        return "\n".join(lines)


def evaluate(plant: ctl.TransferFunction, compensator: Compensator,
             sensor: ctl.TransferFunction | None = None,
             locus_K_max: float | None = None,
             locus: RootLocusData | None = None) -> DesignSummary:
    """
    Compensator + plant → everything the designer displays.

    The root locus is computed for the *unit-gain* compensator ``C/K``, so the
    locus itself does not move when the gain slider does: dragging a pole
    changes where you are on a fixed curve, which is what makes the gesture
    legible. The compensator's own gain is then just a position on it.

    Pass ``locus`` back in when only the gain has changed. The locus is four
    hundred polynomial root solves and it does not depend on the gain, so
    recomputing it on every drag event is the one thing that would make the
    gesture feel slow.
    """
    unit = Compensator(1.0, list(compensator.zeros), list(compensator.poles))
    H = sensor if sensor is not None else ctl.TransferFunction([1], [1])
    L_unit = unit.tf() * plant * H
    L = compensator.tf() * plant * H
    T = ctl.feedback(compensator.tf() * plant, H)

    if locus is None:
        locus = root_locus(L_unit, K_max=locus_K_max)
    poles = closed_loop_poles(L_unit, float(compensator.gain))
    stable = bool(len(poles)) and all(p.real < 0 for p in poles)

    bd = bode(L)
    metrics = None
    note = ""
    if stable:
        try:
            metrics = compute_step_metrics(step_response(T))
        except Exception as exc:                            # noqa: BLE001
            note = f"step metrics unavailable: {exc}"
    else:
        note = ("The closed loop has poles in the right half plane, so there "
                "is no settling time to report.")

    return DesignSummary(
        compensator=compensator, L=L, T=T, locus=locus,
        closed_loop_poles=poles,
        gm_dB=bd.gm_dB, pm_deg=bd.pm_deg, wc=bd.wc, w180=bd.w180,
        stable=stable, metrics=metrics, note=note,
    )


def damping_ray(zeta: float, radius: float) -> np.ndarray:
    """
    The constant-ζ ray for the root-locus overlay: ``s = −ζωn ± jωn√(1−ζ²)``.

    Returned as a 2-point path from the origin, upper half only; the renderer
    mirrors it.
    """
    zeta = float(np.clip(zeta, 0.0, 1.0))
    angle = np.arccos(zeta)
    return np.array([0.0 + 0j,
                     radius * complex(-np.cos(angle), np.sin(angle))])

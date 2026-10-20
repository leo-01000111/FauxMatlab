"""
Classical Bode asymptotes: the straight-line sketch you draw by hand.
======================================================================

Before anyone had a plotter, a Bode diagram was sketched from the poles and
zeros: a straight line whose slope changes by ±20 dB/decade at every corner
frequency. The sketch is what the course teaches, and it is what an exam asks
for, so the viewer draws it over the exact response and lets you compare.

This module is Qt-free and returns plain segments, so every slope and every
end-point can be checked against a hand calculation (``tests/test_asymptotes``).

Conventions
-----------
Write ``G(s) = K · s^(−m) · Π(1 ± s/zᵢ) / Π(1 ± s/pᵢ) · (complex pairs)`` — the
*Bode form*, where every factor is normalised to 1 at ω → 0. ``K`` is the
**Bode gain** (the static gain when there is no integrator), and ``m`` is the
number of integrators minus the number of differentiators.

Magnitude
    * Below the first corner the line is ``20·log10|K| − 20·m·log10 ω``: slope
      ``−20·m`` dB/dec, passing through ``|K|`` dB at 1 rad/s.
    * Each real pole or zero at ``|r|`` bends the slope by ∓/±20 dB/dec; each
      complex pair at ``ωn`` by ∓/±40 dB/dec.
    * A right-half-plane root breaks at the same ``|r|`` with the **same**
      magnitude slope as its mirror image: ``|1 − jω/a| = |1 + jω/a|``.
      Only the phase tells them apart.

Phase (the convention chosen here)
    * Every real first-order factor contributes ±90°, spread **linearly in
      log ω over one decade either side of its corner**: nothing below
      ``r/10``, half (±45°) at ``r`` and all of it above ``10·r`` — the classic
      "0.1 to 10" rule. That is a slope of ±45°/decade.
    * A complex pair contributes ±180° as a **step at ωn**. The decade rule
      would be a poor picture of it: the lightly damped pairs that matter most
      swing through their 180° almost instantly, and the smoother the damping
      the more the step is a coarse but honest average. The jump is reported as
      a discontinuity between two segments, not hidden inside a slope.
    * Poles and zeros swap sign: LHP pole −90°, LHP zero +90°, RHP pole +90°,
      RHP zero −90° (opposite to the LHP mirror; this is what makes
      ``(1−s)/(1+s)`` go to −180°).
    * Each integrator is −90° at every frequency, each differentiator +90°.
    * A negative Bode gain adds −180° (reported modulo 360° to sit on the same
      branch as the plotted phase; see ``phase_anchor``).

Roots numerically indistinguishable from a real double root (a conjugate pair
with a vanishing imaginary part) are treated as two real roots. That matters:
``np.roots`` returns ``−1 ± 1e-8j`` for ``(s+1)²`` and the honest reading is a
double corner with two ramps, not one 180° step.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

#: Relative imaginary part below which a "complex" root is really a real one.
_REAL_TOL = 1e-4
#: |root| below this is a root at the origin (an integrator/differentiator).
_ZERO_TOL = 1e-9


@dataclass(frozen=True)
class AsymptoteSegment:
    """One straight piece of an asymptote, in (log ω, value) coordinates."""

    omega_start: float
    value_start: float
    omega_end: float
    value_end: float
    slope: float            # per decade of ω, in ``unit`` per decade
    unit: str               # "dB" or "°"

    @property
    def decades(self) -> float:
        return float(np.log10(self.omega_end / self.omega_start))

    def describe(self) -> str:
        """``−40 dB/dec  from (0.2 rad/s, 14 dB) to (0.5 rad/s, −2 dB)``."""
        gap = " " if self.unit != "°" else ""
        return (f"{_signed(self.slope)}{gap}{self.unit}/dec  from "
                f"({_g(self.omega_start)} rad/s, "
                f"{_g(self.value_start)}{gap}{self.unit}) "
                f"to ({_g(self.omega_end)} rad/s, "
                f"{_g(self.value_end)}{gap}{self.unit})")


@dataclass(frozen=True)
class AsymptoteBreak:
    """A corner of the magnitude sketch."""

    omega: float
    mag_dB: float           # height of the asymptote at the corner
    slope_change: float     # dB/dec, summed over coincident corners
    description: str        # "pole", "zero pair", "RHP zero", ...


@dataclass
class BodeAsymptotes:
    magnitude: list[AsymptoteSegment] = field(default_factory=list)
    phase: list[AsymptoteSegment] = field(default_factory=list)
    breaks: list[AsymptoteBreak] = field(default_factory=list)
    #: 20·log10|K_bode|, the height of the low-frequency line at 1 rad/s.
    gain_dB: float = float("nan")
    #: −20·(integrators − differentiators), the slope below the first corner.
    low_frequency_slope: float = 0.0


# ──────────────────────────────────────────────────────────────
#  Formatting (shared with the hover text)
# ──────────────────────────────────────────────────────────────

def _g(v: float) -> str:
    """Four significant figures with a typographic minus."""
    if abs(v) < 5e-5:
        v = 0.0
    return f"{v:.4g}".replace("-", "−")


def _signed(v: float) -> str:
    if abs(v) < 5e-5:
        return "0"
    return ("+" if v > 0 else "−") + f"{abs(v):.4g}"


# ──────────────────────────────────────────────────────────────
#  Factorisation
# ──────────────────────────────────────────────────────────────

@dataclass
class _Factors:
    gain: float                         # Bode gain (signed)
    integrators: int                    # net: poles at 0 minus zeros at 0
    real: list[tuple[float, int, bool]]      # (|r|, +1 zero / −1 pole, rhp)
    pairs: list[tuple[float, int, bool]]     # (ωn, +1 zero / −1 pole, rhp)


def _split_roots(roots: np.ndarray):
    """(#origin, real roots, complex-pair roots with Im>0)."""
    origin = 0
    real: list[float] = []
    pairs: list[complex] = []
    for r in np.atleast_1d(roots):
        r = complex(r)
        if abs(r) < _ZERO_TOL:
            origin += 1
        elif abs(r.imag) <= _REAL_TOL * abs(r):
            real.append(r.real)
        elif r.imag > 0:
            pairs.append(r)
    return origin, real, pairs


def _factorise(tf) -> _Factors | None:
    num = np.trim_zeros(np.atleast_1d(np.asarray(tf.num[0][0], dtype=float)), "f")
    den = np.trim_zeros(np.atleast_1d(np.asarray(tf.den[0][0], dtype=float)), "f")
    if len(num) == 0 or len(den) == 0:
        return None
    k = num[0] / den[0]
    z0, zr, zc = _split_roots(np.roots(num) if len(num) > 1 else [])
    p0, pr, pc = _split_roots(np.roots(den) if len(den) > 1 else [])

    # Bode gain: K · Π(−zᵢ) / Π(−pᵢ) over the non-origin roots. A conjugate
    # pair contributes |r|² in both numerator and denominator.
    gain = k
    for z in zr:
        gain *= -z
    for z in zc:
        gain *= abs(z) ** 2
    for p in pr:
        gain /= -p
    for p in pc:
        gain /= abs(p) ** 2

    real = ([(abs(z), +1, z > 0) for z in zr]
            + [(abs(p), -1, p > 0) for p in pr])
    pairs = ([(abs(z), +1, z.real > 0) for z in zc]
             + [(abs(p), -1, p.real > 0) for p in pc])
    return _Factors(float(gain), p0 - z0, real, pairs)


# ──────────────────────────────────────────────────────────────
#  Public entry point
# ──────────────────────────────────────────────────────────────

def bode_asymptotes(tf, omega_min: float, omega_max: float,
                    phase_anchor: float | None = None) -> BodeAsymptotes:
    """
    The classical asymptotes of SISO ``tf`` over ``[omega_min, omega_max]``.

    ``phase_anchor`` is the plotted phase at ``omega_min`` (degrees); the
    phase sketch is shifted by a multiple of 360° to sit on the same branch as
    the exact curve, which python-control unwraps from wherever it starts.
    Corners outside the window still shape the lines inside it.
    """
    if not (0 < omega_min < omega_max):
        raise ValueError("need 0 < omega_min < omega_max")
    f = _factorise(tf)
    if f is None or f.gain == 0.0:
        return BodeAsymptotes()

    out = BodeAsymptotes()
    out.gain_dB = 20.0 * np.log10(abs(f.gain))
    out.low_frequency_slope = -20.0 * f.integrators

    # ── magnitude ──
    corners: dict[float, tuple[float, list[str]]] = {}
    for wn, sign, rhp in f.real:
        _accumulate(corners, wn, sign * 20.0,
                    f"{'RHP ' if rhp else ''}{'zero' if sign > 0 else 'pole'}")
    for wn, sign, rhp in f.pairs:
        _accumulate(corners, wn, sign * 40.0,
                    f"{'RHP ' if rhp else ''}{'zero' if sign > 0 else 'pole'} pair")
    ordered = sorted(corners.items())

    def mag_at(w: float) -> float:
        total = out.gain_dB + out.low_frequency_slope * np.log10(w)
        for wc, (change, _names) in ordered:
            if w > wc:
                total += change * np.log10(w / wc)
        return float(total)

    for wc, (change, names) in ordered:
        if abs(change) > 1e-9:
            out.breaks.append(AsymptoteBreak(
                wc, mag_at(wc), change, " + ".join(names)))

    edges = [omega_min] + [wc for wc, _ in ordered
                           if omega_min < wc < omega_max] + [omega_max]
    for a, b in zip(edges[:-1], edges[1:]):
        out.magnitude.append(_segment(a, mag_at(a), b, mag_at(b), "dB"))
    out.magnitude = _merge(out.magnitude)

    # ── phase ──
    # LHP pole (sign −1) → −90°, LHP zero → +90°; a RHP root flips the sign.
    ramps = [(wn, sign * 90.0 * (-1 if rhp else 1))
             for wn, sign, rhp in f.real]
    steps = [(wn, sign * 180.0 * (-1 if rhp else 1))
             for wn, sign, rhp in f.pairs]
    offset = -90.0 * f.integrators + (-180.0 if f.gain < 0 else 0.0)
    if phase_anchor is not None:
        start = _phase_at(np.log10(omega_min), "right", offset, ramps, steps)
        offset += 360.0 * np.round((phase_anchor - start) / 360.0)

    xs = {float(np.log10(omega_min)), float(np.log10(omega_max))}
    for wn, _ in ramps:
        xs.update((np.log10(wn) - 1.0, np.log10(wn) + 1.0))
    for wn, _ in steps:
        xs.add(float(np.log10(wn)))
    lo, hi = np.log10(omega_min), np.log10(omega_max)
    cuts = sorted(x for x in xs if lo - 1e-12 <= x <= hi + 1e-12)
    cuts[0], cuts[-1] = lo, hi
    for a, b in zip(cuts[:-1], cuts[1:]):
        if b - a < 1e-12:
            continue
        out.phase.append(_segment(
            10 ** a, _phase_at(a, "right", offset, ramps, steps),
            10 ** b, _phase_at(b, "left", offset, ramps, steps), "°"))
    out.phase = _merge(out.phase)
    return out


def _accumulate(corners, wn: float, change: float, name: str) -> None:
    """Coincident corners (a double pole) add up rather than overlap."""
    for key in corners:
        if abs(key - wn) <= 1e-9 * wn:
            old, names = corners[key]
            corners[key] = (old + change, names + [name])
            return
    corners[wn] = (change, [name])


def _phase_at(x: float, side: str, offset: float, ramps, steps) -> float:
    """Phase sketch at log10 ω = ``x``; ``side`` picks the limit at a step."""
    total = offset
    for wn, amp in ramps:
        frac = np.clip((x - (np.log10(wn) - 1.0)) / 2.0, 0.0, 1.0)
        total += amp * frac
    for wn, amp in steps:
        xs = np.log10(wn)
        if x > xs + 1e-12 or (side == "right" and abs(x - xs) <= 1e-12):
            total += amp
    return float(total)


def _segment(w0: float, v0: float, w1: float, v1: float,
             unit: str) -> AsymptoteSegment:
    decades = np.log10(w1 / w0)
    slope = (v1 - v0) / decades if decades > 0 else 0.0
    slope += 0.0   # −0.0 → 0.0
    # Snap the arithmetic noise: slopes are multiples of 5 by construction.
    if abs(slope - round(slope)) < 1e-6:
        slope = float(round(slope))
    return AsymptoteSegment(float(w0), float(v0), float(w1), float(v1),
                            float(slope), unit)


def _merge(segments: list[AsymptoteSegment]) -> list[AsymptoteSegment]:
    """Join neighbours that continue in a straight line (cancelled corners)."""
    merged: list[AsymptoteSegment] = []
    for seg in segments:
        if merged:
            prev = merged[-1]
            continuous = abs(prev.value_end - seg.value_start) < 1e-9
            if continuous and abs(prev.slope - seg.slope) < 1e-9:
                merged[-1] = _segment(prev.omega_start, prev.value_start,
                                      seg.omega_end, seg.value_end, seg.unit)
                continue
        merged.append(seg)
    return merged

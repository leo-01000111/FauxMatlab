"""
Discrete time: sampling, the Jury criterion, deadbeat control.
==============================================================
Sampling maps the left half-plane onto the unit disc through ``z = e^{sT}``.
Everything from the continuous half carries over with that substitution — the
imaginary axis becomes the unit circle, and "stable" becomes ``|z| < 1``.

What does not carry over is that the map is many-to-one: frequencies above
``π/T`` alias down, so a controller sampled too slowly sees a different plant
from the one you designed against. The sample-rate sweep here exists to make
that visible rather than surprising.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import control as ctl
import numpy as np
from scipy.linalg import logm

#: Discretisation methods ``c2d`` accepts.
METHODS = ("zoh", "tustin", "bilinear", "euler", "backward_diff", "matched")


class DiscreteError(ValueError):
    """A discrete-time operation could not be carried out."""


# ──────────────────────────────────────────────────────────────
#  Sampling
# ──────────────────────────────────────────────────────────────

def c2d(sys, dt: float, method: str = "zoh", prewarp: float | None = None):
    """
    Discretise a continuous model.

    ``zoh`` is what a real D/A converter does and is exact for a
    piecewise-constant input. ``tustin`` maps the whole left half-plane into
    the unit disc — so it never turns a stable system unstable — but warps the
    frequency axis; give ``prewarp`` to make it exact at one chosen frequency.
    """
    if dt <= 0:
        raise DiscreteError(f"the sample time must be positive, got {dt}")
    if method not in METHODS:
        raise DiscreteError(
            f"unknown method {method!r}; use one of {', '.join(METHODS)}")
    try:
        if prewarp is not None and method in ("tustin", "bilinear"):
            return ctl.sample_system(sys, dt, method="bilinear",
                                     prewarp_frequency=prewarp)
        return ctl.sample_system(sys, dt, method=method)
    except Exception as exc:
        raise DiscreteError(f"discretisation failed: {exc}") from exc


def d2c(sys, method: str = "zoh"):
    """
    Recover a continuous model from a discrete one.

    python-control 0.10 has no ``d2c``, so it is implemented here. For ``zoh``
    the inverse is the matrix logarithm::

        A = log(A_d)/T          B = A·(A_d − I)⁻¹·B_d

    which is exact when a continuous model exists. It may not: a discrete
    system with a negative real eigenvalue has no real logarithm, because no
    continuous system sampled at that rate produces it. That case is reported
    rather than approximated.
    """
    dt = getattr(sys, "dt", None)
    if not dt:
        raise DiscreteError("this system is already continuous-time")

    if method in ("tustin", "bilinear"):
        return _d2c_tustin(sys, dt)
    if method != "zoh":
        raise DiscreteError(
            f"d2c supports 'zoh' and 'tustin'; got {method!r}")

    ss = ctl.tf2ss(sys) if isinstance(sys, ctl.TransferFunction) else sys
    Ad = np.atleast_2d(np.asarray(ss.A, dtype=float))
    Bd = np.atleast_2d(np.asarray(ss.B, dtype=float))

    eigenvalues = np.linalg.eigvals(Ad)
    if np.any((np.abs(eigenvalues.imag) < 1e-12) & (eigenvalues.real <= 0)):
        raise DiscreteError(
            "this discrete system has a real non-positive eigenvalue, so it "
            "has no real continuous equivalent — no continuous system sampled "
            "at this rate could produce it. Try the 'tustin' inverse, which "
            "always returns something, at the cost of being approximate."
        )

    A = np.real(logm(Ad)) / dt
    try:
        B = A @ np.linalg.solve(Ad - np.eye(Ad.shape[0]), Bd)
    except np.linalg.LinAlgError as exc:
        raise DiscreteError(
            "A_d − I is singular (the system has an integrator), so the ZOH "
            "inverse is not defined; use the 'tustin' inverse instead."
        ) from exc
    return ctl.ss(A, B, np.asarray(ss.C), np.asarray(ss.D))


def _d2c_tustin(sys, dt: float):
    """Invert the bilinear map ``s = (2/T)(z−1)/(z+1)``."""
    ss = ctl.tf2ss(sys) if isinstance(sys, ctl.TransferFunction) else sys
    Ad = np.atleast_2d(np.asarray(ss.A, dtype=float))
    Bd = np.atleast_2d(np.asarray(ss.B, dtype=float))
    Cd = np.atleast_2d(np.asarray(ss.C, dtype=float))
    Dd = np.atleast_2d(np.asarray(ss.D, dtype=float))
    n = Ad.shape[0]
    eye = np.eye(n)

    try:
        inv = np.linalg.inv(Ad + eye)
    except np.linalg.LinAlgError as exc:
        raise DiscreteError(
            "A_d + I is singular (an eigenvalue sits at z = −1), so the "
            "bilinear map cannot be inverted") from exc

    A = (2.0 / dt) * inv @ (Ad - eye)
    B = (2.0 / np.sqrt(dt)) * inv @ Bd
    C = (2.0 / np.sqrt(dt)) * Cd @ inv
    D = Dd - Cd @ inv @ Bd
    return ctl.ss(A, B, C, D)


def compare_methods(sys, dt: float,
                    methods=("zoh", "tustin", "euler")) -> dict:
    """
    Discretise the same system several ways, for side-by-side comparison.

    Returns ``{method: discrete system}``, skipping any the library refuses.
    The differences are largest near the Nyquist frequency, which is the point
    worth seeing.
    """
    out = {}
    for method in methods:
        try:
            out[method] = c2d(sys, dt, method)
        except DiscreteError:
            continue
    return out


# ──────────────────────────────────────────────────────────────
#  Jury stability criterion
# ──────────────────────────────────────────────────────────────

@dataclass
class JuryResult:
    """The discrete analogue of a Routh table."""
    table:       list[list[float]]
    coefficients: list[float]
    stable:      bool
    conditions:  list[tuple[str, bool, float]]   # (description, passed, value)
    n_outside:   int                             # roots with |z| ≥ 1
    notes:       list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = ["stable (all roots inside the unit circle)" if self.stable
                 else f"UNSTABLE — {self.n_outside} root(s) on or outside the "
                      f"unit circle"]
        for text, passed, value in self.conditions:
            lines.append(f"  {'✓' if passed else '✗'} {text}   ({value:.6g})")
        lines.extend(f"⚠ {n}" for n in self.notes)
        return "\n".join(lines)


def jury(coefficients) -> JuryResult:
    """
    Jury's criterion: are all roots of ``a(z)`` inside the unit circle?

    The discrete counterpart of Routh–Hurwitz, and the same trick — decide
    stability from the coefficients without computing the roots. Coefficients
    are given highest power first.

    The three necessary conditions are checked first (``a(1) > 0``,
    ``(−1)ⁿa(−1) > 0``, ``|a₀| < aₙ``); the table then supplies the rest.
    """
    a = [float(c) for c in np.atleast_1d(np.asarray(coefficients,
                                                    dtype=float)).ravel()]
    if len(a) < 2:
        raise DiscreteError("give at least a first-order polynomial")
    if abs(a[0]) < 1e-300:
        raise DiscreteError("the leading coefficient must be non-zero")

    # Normalise so the leading coefficient is positive; this flips every sign
    # together and leaves the roots unchanged.
    if a[0] < 0:
        a = [-c for c in a]
    n = len(a) - 1

    a1 = float(np.polyval(a, 1.0))
    am1 = float(np.polyval(a, -1.0)) * ((-1) ** n)
    conditions = [
        ("a(1) > 0", a1 > 0, a1),
        (f"(−1)^{n}·a(−1) > 0", am1 > 0, am1),
        ("|a₀| < aₙ", abs(a[-1]) < a[0], abs(a[-1]) - a[0]),
    ]

    # Jury's array. Each new row is formed from the determinants of the
    # outer pairs of the previous row against its own reverse.
    row = list(a)
    table: list[list[float]] = [list(row), list(reversed(row))]
    for _ in range(n - 1):
        if len(row) < 2:
            break
        first, last = row[0], row[-1]
        nxt = [first * row[i] - last * row[len(row) - 1 - i]
               for i in range(len(row) - 1)]
        table.append(list(nxt))
        table.append(list(reversed(nxt)))
        conditions.append((f"|first| > |last| in row of length {len(nxt)}",
                           abs(nxt[0]) > abs(nxt[-1]),
                           abs(nxt[0]) - abs(nxt[-1])))
        row = nxt

    stable = all(passed for _text, passed, _v in conditions)
    roots = np.roots(a)
    n_outside = int(np.sum(np.abs(roots) >= 1.0 - 1e-12))

    notes = []
    if stable != (n_outside == 0):
        notes.append(
            f"the Jury conditions and the computed roots disagree "
            f"({n_outside} root(s) outside); a root very close to the unit "
            f"circle makes both tests delicate")

    return JuryResult(table=table, coefficients=a, stable=stable,
                      conditions=conditions, n_outside=n_outside, notes=notes)


def jury_from_system(sys) -> JuryResult:
    """Run :func:`jury` on a discrete system's characteristic polynomial."""
    if not getattr(sys, "dt", None):
        raise DiscreteError(
            "Jury's criterion applies to discrete-time systems; use the "
            "Routh criterion for a continuous one")
    tf = ctl.ss2tf(sys) if isinstance(sys, ctl.StateSpace) else sys
    return jury(np.atleast_1d(tf.den[0][0]))


# ──────────────────────────────────────────────────────────────
#  Deadbeat
# ──────────────────────────────────────────────────────────────

def deadbeat(sys) -> np.ndarray:
    """
    State feedback placing every closed-loop eigenvalue at ``z = 0``.

    ``A − BK`` becomes nilpotent, so the state reaches zero **exactly** after
    ``n`` samples rather than asymptotically — a response with no continuous
    analogue at all.

    It is fast precisely because it asks for large control signals, and it is
    fragile: with every pole at the origin there is no margin anywhere, so a
    small model error shows up immediately. Worth demonstrating, rarely worth
    shipping.
    """
    if not getattr(sys, "dt", None):
        raise DiscreteError(
            "deadbeat control is a discrete-time idea: it places the poles at "
            "z = 0, which has no continuous equivalent. Sample the system "
            "first with c2d().")

    n = sys.nstates

    # Ackermann's formula, not the robust placement routine. Deadbeat needs
    # *n identical* poles at the origin, which the robust algorithm cannot
    # express: it refuses repeated poles beyond the number of inputs, and
    # spreading them by a small ε leaves A − BK merely near-nilpotent, with
    # eigenvectors so ill-conditioned that ‖(A−BK)ⁿ‖ stays far above zero —
    # the response then takes n+1 samples instead of n. Ackermann is a
    # closed-form expression in the coefficients and gives an exactly
    # nilpotent result.
    B = np.atleast_2d(np.asarray(sys.B, dtype=float))
    if B.shape[1] != 1:
        raise DiscreteError(
            f"deadbeat design here is single-input; this system has "
            f"{B.shape[1]} inputs")
    return np.atleast_2d(
        np.asarray(ctl.acker(np.asarray(sys.A), B, [0.0] * n), dtype=float))


def settling_samples(sys, K: np.ndarray, tol: float = 1e-9,
                     max_samples: int = 200) -> int:
    """How many samples ``(A − BK)ᵏ`` takes to become negligible."""
    A = np.atleast_2d(np.asarray(sys.A, dtype=float))
    B = np.atleast_2d(np.asarray(sys.B, dtype=float))
    M = A - B @ np.atleast_2d(np.asarray(K, dtype=float))
    power = np.eye(M.shape[0])
    for k in range(1, max_samples + 1):
        power = power @ M
        if np.max(np.abs(power)) < tol:
            return k
    return max_samples


# ──────────────────────────────────────────────────────────────
#  Sample-rate effects
# ──────────────────────────────────────────────────────────────

def sample_rate_sweep(sys, sample_times, method: str = "zoh",
                      close_loop: bool = False) -> dict:
    """
    Discretise at several rates and report what sampling costs.

    Returns ``{dt: {"sys", "poles", "stable", "nyquist", …}}``.

    Pass ``close_loop=True`` and a loop transfer function ``L`` to see the
    effect that matters: sampling adds roughly ``ωT/2`` of phase lag — half a
    sample period of delay — which eats phase margin and eventually
    destabilises a loop that was comfortable in continuous time. Sweeping the
    *closed* loop instead shows nothing, because a zero-order hold maps the
    left half-plane into the unit disc and cannot turn a stable system
    unstable.
    """
    # The lag a zero-order hold adds is ωT/2 radians, so it is only meaningful
    # at a stated frequency — the loop's gain crossover is the one that
    # decides stability.
    wc = float("nan")
    try:
        wc = float(ctl.stability_margins(sys)[4])
    except Exception:
        pass

    out = {}
    for dt in sample_times:
        dt = float(dt)
        try:
            discrete = c2d(sys, dt, method)
        except DiscreteError as exc:
            out[dt] = {"error": str(exc)}
            continue

        analysed = discrete
        if close_loop:
            try:
                analysed = ctl.feedback(discrete, 1)
            except Exception as exc:
                out[dt] = {"error": f"could not close the loop: {exc}"}
                continue

        poles = np.atleast_1d(ctl.poles(analysed))
        out[dt] = {
            "sys": discrete,
            "closed_loop": analysed if close_loop else None,
            "poles": poles,
            "max_magnitude": float(np.max(np.abs(poles))) if len(poles) else 0.0,
            "stable": bool(np.all(np.abs(poles) < 1.0)),
            "nyquist": float(np.pi / dt),
            # Extra phase lag the hold contributes where it matters.
            "phase_lag_at_wc_deg": (float(np.degrees(wc * dt / 2.0))
                                    if np.isfinite(wc) else float("nan")),
            "wc": wc,
        }
    return out


def unit_circle(n: int = 400) -> tuple[np.ndarray, np.ndarray]:
    """Points on the unit circle, for the discrete pole map."""
    theta = np.linspace(0, 2 * np.pi, n)
    return np.cos(theta), np.sin(theta)


def damping_from_z(z: complex, dt: float) -> tuple[float, float]:
    """
    ``(ζ, ωn)`` of the continuous pole a discrete pole ``z`` corresponds to.

    Inverts ``z = e^{sT}``, which is how a discrete pole is read in the terms
    the course uses: ``|z|`` sets the decay and ``arg z`` the frequency.
    """
    if abs(z) < 1e-300:
        return 1.0, float("inf")            # deadbeat: infinitely fast
    s = np.log(complex(z)) / dt
    wn = float(abs(s))
    if wn < 1e-300:
        return float("nan"), 0.0
    return float(-s.real / wn), wn

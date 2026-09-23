"""
Automatic PID tuning by loop shaping — the PID Tuner's arithmetic.
==================================================================

MATLAB's PID Tuner gives you two sliders, **response time** and **transient
behaviour**, and hides what they do. They set a target crossover frequency and
a target phase margin; the tuner then picks controller gains that put the loop
exactly there.

That is what this module does, and it does it in closed form rather than by
search. At the target crossover ``ωc`` two conditions must hold:

    |C(jωc)·G(jωc)| = 1              (ωc is the gain crossover)
    ∠C(jωc) + ∠G(jωc) = −180° + φm   (the phase margin there is φm)

so the controller's required magnitude ``M = 1/|G(jωc)|`` and phase ``θ`` are
both known before any gains are chosen. A PI has exactly two free parameters,
so those two equations determine it outright. A PID has three, and the extra
freedom is spent on the classical ``Ti = 4·Td`` ratio.

The consequence worth stating: **the achieved margin is exact, not
approximate** — ``margin(C·G)`` returns the requested ``ωc`` and ``φm`` to
numerical precision. Where the design can fail it fails visibly: a PI cannot
add phase, so asking one for a crossover above the plant's own phase budget
returns an infeasible result that names the reason, rather than gains that
quietly do something else.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import control as ctl
import numpy as np

from .freqresp import bode, response
from .timeresp import StepMetrics, compute_step_metrics, step_response
from .tuning import PIDParams, pid_tf


class PIDKind(str, Enum):
    P = "P"
    PI = "PI"
    PD = "PD"
    PID = "PID"


#: The ``Ti/Td`` ratio that spends a PID's third degree of freedom. Four is
#: the classical choice — it is what the Ziegler–Nichols PID rule produces
#: (``Ti = 2L``, ``Td = 0.5L``) and it keeps the two controller zeros real.
DEFAULT_TI_OVER_TD = 4.0

#: Phase margin at the two ends of the transient-behaviour slider.
PM_AGGRESSIVE = 45.0
PM_ROBUST = 75.0


@dataclass
class TuneResult:
    """A tuning attempt — successful or not, but always explained."""

    kind: PIDKind
    params: PIDParams
    C: ctl.TransferFunction
    L: ctl.TransferFunction
    T: ctl.TransferFunction
    target_wc: float
    target_pm_deg: float
    achieved_wc: float
    achieved_pm_deg: float
    achieved_gm_dB: float
    required_phase_deg: float
    feasible: bool
    stable: bool
    metrics: StepMetrics | None = None
    note: str = ""

    @property
    def response_time(self) -> float:
        """
        The slider's own units: roughly ``2/ωc`` seconds.

        An estimate of the closed-loop rise time from the bandwidth, exact
        only for a first-order loop. :attr:`metrics` carries the simulated
        value, which is the one to trust.
        """
        return float(2.0 / self.achieved_wc) if self.achieved_wc > 0 \
            else float("inf")

    def describe(self) -> str:
        if not self.feasible:
            return f"No {self.kind.value} controller meets this target.\n{self.note}"
        lines = [
            f"{self.kind.value}:  Kp = {self.params.Kp:.5g}"
            + (f"   Ki = {self.params.Ki:.5g}" if self.params.Ki else "")
            + (f"   Kd = {self.params.Kd:.5g}" if self.params.Kd else "")
            + (f"   Tf = {self.params.Tf:.5g}" if self.params.Tf else ""),
            f"ωc = {self.achieved_wc:.4g} rad/s (target {self.target_wc:.4g})"
            f"    PM = {self.achieved_pm_deg:.1f}° "
            f"(target {self.target_pm_deg:.1f}°)"
            f"    GM = {self.achieved_gm_dB:.2f} dB",
        ]
        if self.metrics is not None:
            lines.append(
                f"overshoot {self.metrics.Mp_pct:.1f}%    "
                f"rise {self.metrics.tr_1090:.3g} s    "
                f"settle(±2%) {self.metrics.ts_2pct:.3g} s")
        if self.note:
            lines.append(self.note)
        return "\n".join(lines)


# ──────────────────────────────────────────────────────────────
#  The sliders
# ──────────────────────────────────────────────────────────────

def phase_margin_for(transient: float) -> float:
    """
    Transient-behaviour slider → target phase margin.

    ``0`` is aggressive (45°, fast and peaky), ``1`` is robust (75°, slow and
    smooth), and the default ``0.5`` lands on 60° — the textbook value.
    """
    b = float(np.clip(transient, 0.0, 1.0))
    return PM_AGGRESSIVE + b * (PM_ROBUST - PM_AGGRESSIVE)


#: The controller phase each structure is aimed at when it picks its own
#: crossover.
#:
#: Zero means "put the crossover where the plant already has the phase the
#: margin needs", which leaves the controller nothing to do but set the gain.
#: That is right for a PID, whose ``Ti = 4·Td`` ratio still gives it real
#: integral and derivative action there — but wrong for a PI, which would come
#: back with ``Ki ≈ 0``, a proportional controller wearing a PI's name and
#: none of its steady-state accuracy. So a PI aims a little below the neutral
#: frequency and a PD a little above, where each has something to contribute.
NEUTRAL_PHASE: dict[str, float] = {
    "P": 0.0,
    "PI": -25.0,
    "PD": +25.0,
    "PID": 0.0,
}


def default_crossover(G: ctl.TransferFunction, pm_deg: float = 60.0,
                      controller_phase_deg: float = 0.0) -> float:
    """
    A sensible starting crossover: where the plant's phase leaves the
    controller exactly ``controller_phase_deg`` to supply.

    With the default of zero that is where the plant *already* has the phase
    the target margin needs — the least strained place to close the loop, and
    a natural centre for the response-time slider to move around.

    Plants whose phase never reaches that value — a double integrator sits at
    −180° everywhere — fall back to the geometric mean of their non-zero pole
    and zero magnitudes, which is where their dynamics actually live.
    """
    omega = np.logspace(-3, 3, 2000)
    _, phase = response(G, omega)
    phase_deg = np.degrees(np.unwrap(phase))
    target = -180.0 + float(pm_deg) - float(controller_phase_deg)

    crossings = np.nonzero(np.diff(np.sign(phase_deg - target)))[0]
    if len(crossings):
        i = int(crossings[0])
        x0, x1 = np.log10(omega[i]), np.log10(omega[i + 1])
        y0, y1 = phase_deg[i], phase_deg[i + 1]
        if abs(y1 - y0) > 1e-12:
            return float(10 ** (x0 + (target - y0) * (x1 - x0) / (y1 - y0)))
        return float(omega[i])

    roots = np.concatenate([np.atleast_1d(ctl.poles(G)),
                            np.atleast_1d(ctl.zeros(G))])
    magnitudes = [abs(r) for r in roots if abs(r) > 1e-9]
    if magnitudes:
        return float(np.clip(np.exp(np.mean(np.log(magnitudes))), 1e-3, 1e3))
    return 1.0


def crossover_for(G: ctl.TransferFunction, speed: float,
                  pm_deg: float = 60.0,
                  kind: PIDKind | str = "PID") -> float:
    """
    Response-time slider → target crossover.

    ``speed`` runs −1 … +1 over two decades either side of
    :func:`default_crossover`, so one slider spans four decades of closed-loop
    bandwidth, and 0 leaves the plant where it naturally wants to be.
    """
    neutral = default_crossover(G, pm_deg,
                                NEUTRAL_PHASE[PIDKind(kind).value])
    return float(neutral * 10.0 ** (2.0 * float(speed)))


# ──────────────────────────────────────────────────────────────
#  Tuning
# ──────────────────────────────────────────────────────────────

def tune(G: ctl.TransferFunction, kind: PIDKind | str = PIDKind.PI,
         wc: float | None = None, pm_deg: float = 60.0,
         Tf: float = 0.0,
         ti_over_td: float = DEFAULT_TI_OVER_TD) -> TuneResult:
    """
    Tune a controller of type ``kind`` for crossover ``wc`` and margin
    ``pm_deg``.

    ``Tf`` filters the derivative term. It is applied *after* the gains are
    solved, so it perturbs the achieved margin slightly; the result reports
    what was actually achieved, not what was asked for.
    """
    kind = PIDKind(kind)
    if wc is None:
        wc = default_crossover(G, pm_deg, NEUTRAL_PHASE[kind.value])
    wc = float(wc)
    if wc <= 0:
        raise ValueError(f"crossover must be positive, got {wc}")

    magnitude, phase = response(G, np.array([wc]))
    gain_G = float(magnitude[0])
    phase_G = float(np.degrees(phase[0]))
    if gain_G < 1e-300:
        return _infeasible(kind, G, wc, pm_deg, float("nan"),
                           "The plant has zero gain at this frequency, so no "
                           "finite controller gain can make it cross 0 dB.")

    M = 1.0 / gain_G
    theta = _wrap(-180.0 + float(pm_deg) - phase_G)

    builder = {
        PIDKind.P: _tune_p,
        PIDKind.PI: _tune_pi,
        PIDKind.PD: _tune_pd,
        PIDKind.PID: _tune_pid,
    }[kind]
    params, problem = builder(M, theta, wc, ti_over_td)
    if problem:
        return _infeasible(kind, G, wc, pm_deg, theta, problem)

    params.Tf = float(Tf) if kind in (PIDKind.PD, PIDKind.PID) else 0.0
    return _finish(kind, params, G, wc, pm_deg, theta)


def _tune_p(M: float, theta: float, wc: float,
            _ratio: float) -> tuple[PIDParams, str]:
    """
    Proportional only: one free parameter, so only the crossover is honoured.

    The phase margin is whatever the plant gives at that frequency. It is
    reported rather than targeted — a P controller has no way to change it.
    """
    return PIDParams(Kp=M), ""


def _tune_pi(M: float, theta: float, wc: float,
             _ratio: float) -> tuple[PIDParams, str]:
    """``C = Kp + Ki/s`` → ``C(jωc) = Kp − j·Ki/ωc``, so θ must be negative."""
    if theta > -1e-9:
        return PIDParams(), (
            f"A PI controller only ever *subtracts* phase, but this target "
            f"needs {theta:+.1f}° at ω = {wc:.4g} rad/s. Lower the crossover, "
            f"accept a smaller phase margin, or use a PID.")
    if theta <= -90.0:
        return PIDParams(), (
            f"This target needs {theta:+.1f}° from the controller; a PI can "
            f"supply at most −90°, and only with Kp = 0. The crossover is too "
            f"high for this plant.")
    rad = np.radians(theta)
    return PIDParams(Kp=M * np.cos(rad), Ki=-wc * M * np.sin(rad)), ""


def _tune_pd(M: float, theta: float, wc: float,
             _ratio: float) -> tuple[PIDParams, str]:
    """``C = Kp + Kd·s`` → ``C(jωc) = Kp + j·Kd·ωc``, so θ must be positive."""
    if theta < -1e-9:
        return PIDParams(), (
            f"A PD controller only ever *adds* phase, but this target needs "
            f"{theta:+.1f}° at ω = {wc:.4g} rad/s. Raise the crossover, or "
            f"use a PI or PID.")
    if theta >= 90.0:
        return PIDParams(), (
            f"This target needs {theta:+.1f}°; a PD can supply at most +90°.")
    rad = np.radians(theta)
    return PIDParams(Kp=M * np.cos(rad), Kd=M * np.sin(rad) / wc), ""


def _tune_pid(M: float, theta: float, wc: float,
              ratio: float) -> tuple[PIDParams, str]:
    """
    ``C = Kp(1 + 1/(Ti·s) + Td·s)`` with ``Ti = ratio·Td``.

    Writing ``x = ωc·Td``, the phase condition becomes
    ``tan θ = x − 1/(ratio·x)`` — one quadratic, whose positive root gives
    ``Td``. Both signs of θ are reachable, which is the whole point of having
    an integral and a derivative term at once.
    """
    if abs(theta) >= 90.0:
        return PIDParams(), (
            f"This target needs {theta:+.1f}° from the controller, and no PID "
            f"can exceed ±90°. Move the crossover to where the plant's own "
            f"phase is closer to what the margin needs.")
    rad = np.radians(theta)
    tan = np.tan(rad)
    x = (ratio * tan + np.sqrt(ratio ** 2 * tan ** 2 + 4.0 * ratio)) \
        / (2.0 * ratio)
    if not np.isfinite(x) or x <= 0:
        return PIDParams(), "The phase condition has no positive solution."

    Td = x / wc
    Ti = ratio * Td
    Kp = M * np.cos(rad)
    return PIDParams(Kp=Kp, Ki=Kp / Ti, Kd=Kp * Td), ""


# ──────────────────────────────────────────────────────────────
#  Assembling the result
# ──────────────────────────────────────────────────────────────

def _finish(kind: PIDKind, params: PIDParams, G: ctl.TransferFunction,
            wc: float, pm_deg: float, theta: float) -> TuneResult:
    C = pid_tf(params)
    L = C * G
    T = ctl.feedback(L, 1)
    bd = bode(L)
    poles = np.atleast_1d(ctl.poles(T))
    stable = bool(len(poles)) and all(p.real < 0 for p in poles)

    metrics = None
    note = ""
    if stable:
        try:
            metrics = compute_step_metrics(step_response(T))
        except Exception as exc:                            # noqa: BLE001
            note = f"step metrics unavailable: {exc}"
    else:
        note = ("These gains meet the margin at the target crossover, but the "
                "closed loop is still unstable — the loop must be crossing "
                "0 dB more than once. Try a lower crossover.")

    if kind is PIDKind.P:
        note = (note + "  " if note else "") + (
            f"A P controller has one free parameter, so the crossover is met "
            f"and the margin is whatever the plant gives there "
            f"({bd.pm_deg:.1f}°).")
    elif params.Ki and _has_integrator(G):
        note = (note + "  " if note else "") + (
            "The plant already contains an integrator, so the controller's "
            "adds a second one and the loop starts at −180°. That is why the "
            "crossover lands so low: every degree of phase margin has to come "
            "back from the PI zero. Steady-state error to a ramp is now zero, "
            "which is usually the reason for doing it.")

    return TuneResult(
        kind=kind, params=params, C=C, L=L, T=T,
        target_wc=wc, target_pm_deg=pm_deg,
        achieved_wc=bd.wc, achieved_pm_deg=bd.pm_deg, achieved_gm_dB=bd.gm_dB,
        required_phase_deg=theta, feasible=True, stable=stable,
        metrics=metrics, note=note.strip(),
    )


def _infeasible(kind: PIDKind, G: ctl.TransferFunction, wc: float,
                pm_deg: float, theta: float, why: str) -> TuneResult:
    unity = ctl.TransferFunction([1], [1])
    return TuneResult(
        kind=kind, params=PIDParams(Kp=0.0), C=unity, L=G, T=ctl.feedback(G, 1),
        target_wc=wc, target_pm_deg=pm_deg,
        achieved_wc=float("nan"), achieved_pm_deg=float("nan"),
        achieved_gm_dB=float("nan"), required_phase_deg=theta,
        feasible=False, stable=False, note=why,
    )


def _has_integrator(G: ctl.TransferFunction) -> bool:
    return bool(any(abs(p) < 1e-9 for p in np.atleast_1d(ctl.poles(G))))


def _wrap(degrees: float) -> float:
    """Fold an angle into (−180°, 180°]."""
    return float((degrees + 180.0) % 360.0 - 180.0)


# ──────────────────────────────────────────────────────────────
#  The tuner's two-slider front end
# ──────────────────────────────────────────────────────────────

def tune_by_sliders(G: ctl.TransferFunction, kind: PIDKind | str = PIDKind.PI,
                    speed: float = 0.0, transient: float = 0.5,
                    Tf: float = 0.0) -> TuneResult:
    """
    Tune from the two slider positions the app shows.

    ``speed`` runs −1 (slow) … +1 (fast); ``transient`` runs 0 (aggressive) …
    1 (robust). Both defaults give the balanced design.
    """
    kind = PIDKind(kind)
    pm = phase_margin_for(transient)
    return tune(G, kind, wc=crossover_for(G, speed, pm, kind),
                pm_deg=pm, Tf=Tf)

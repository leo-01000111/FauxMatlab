"""
Steady-state performance analysis (ch.7 of the course).
========================================================
System type, error constants Kp/Kv/Ka, steady-state errors for
step/ramp/parabola, disturbance rejection metrics, bandwidth trade-offs.
"""

from __future__ import annotations

from dataclasses import dataclass

import control as ctl
import numpy as np


# ──────────────────────────────────────────────────────────────
#  Dataclass
# ──────────────────────────────────────────────────────────────

@dataclass
class PerformanceReport:
    """Steady-state and bandwidth performance summary."""
    # System type
    system_type:   int          # 0, 1, 2, … (number of free integrators in L)
    # Error constants
    Kp: float    # position error constant  lim_{s→0} L(s)
    Kv: float    # velocity error constant  lim_{s→0} s·L(s)
    Ka: float    # acceleration error const lim_{s→0} s²·L(s)
    # Steady-state errors (for unity-feedback, unit input of each type)
    ess_step:     float    # 1/(1+Kp)  for type 0; 0 for type ≥ 1
    ess_ramp:     float    # 1/Kv      for type 1; 0 for type ≥ 2; inf type 0
    ess_parabola: float    # 1/Ka      for type 2; 0 for ≥ 3; inf for ≤ 1
    # Disturbance rejection (magnitude of S·G at ω=0 — affects output dist)
    S_dc:    float    # |S(0)|  ≈ 0 if integral action in loop
    T_dc:    float    # |T(0)|
    # Bandwidth
    bw_3dB:  float    # −3 dB BW of T (if available)
    # Summary
    summary: str


def analyse_performance(
    loop_tf: ctl.TransferFunction,
    closed_loop_tf: ctl.TransferFunction | None = None,
    bw_3dB: float | None = None,
) -> PerformanceReport:
    """
    Compute performance metrics for a closed-loop system with loop TF L(s).
    closed_loop_tf is T(s) = L/(1+L); if None, derived internally.
    """
    # System type = number of poles at s=0 in L
    sys_type = _system_type(loop_tf)

    # Error constants
    Kp = _lim_s0(loop_tf, power=0)
    Kv = _lim_s0(loop_tf, power=1)
    Ka = _lim_s0(loop_tf, power=2)

    # Steady-state errors
    ess_step     = _ess_step(sys_type, Kp)
    ess_ramp     = _ess_ramp(sys_type, Kv)
    ess_parabola = _ess_parabola(sys_type, Ka)

    # S and T at DC
    if closed_loop_tf is None:
        try:
            closed_loop_tf = ctl.feedback(loop_tf, ctl.TransferFunction([1], [1]))
        except Exception:
            closed_loop_tf = None

    S_dc, T_dc = _dc_sensitivity(loop_tf, closed_loop_tf)

    # Summary string
    summary_lines = [
        f"System type: {sys_type}",
        f"Kp = {_fmt(Kp)},  Kv = {_fmt(Kv)},  Ka = {_fmt(Ka)}",
        f"e_ss (step)      = {_fmt(ess_step)}",
        f"e_ss (ramp)      = {_fmt(ess_ramp)}",
        f"e_ss (parabola)  = {_fmt(ess_parabola)}",
        f"|S(0)| = {_fmt(S_dc)},  |T(0)| = {_fmt(T_dc)}",
    ]
    if bw_3dB is not None:
        summary_lines.append(f"Bandwidth (−3 dB) = {bw_3dB:.3g} rad/s")

    return PerformanceReport(
        system_type=sys_type,
        Kp=Kp, Kv=Kv, Ka=Ka,
        ess_step=ess_step, ess_ramp=ess_ramp, ess_parabola=ess_parabola,
        S_dc=S_dc, T_dc=T_dc,
        bw_3dB=bw_3dB if bw_3dB is not None else float('nan'),
        summary="\n".join(summary_lines),
    )


# ──────────────────────────────────────────────────────────────
#  Internal helpers
# ──────────────────────────────────────────────────────────────

def _system_type(L: ctl.TransferFunction) -> int:
    """Number of poles of L at s=0."""
    poles = ctl.poles(L)
    return int(sum(1 for p in poles if abs(p) < 1e-6))


def _lim_s0(L: ctl.TransferFunction, power: int) -> float:
    """
    Compute lim_{s→0} s^power · L(s).
    For power=0: Kp,  power=1: Kv,  power=2: Ka.

    Uses sympy to cancel common s factors before evaluating at s=0,
    so pure integrators (1/s, 1/s², …) are handled correctly.
    """
    import sympy as sp
    s = sp.Symbol('s')
    try:
        num_arr = L.num[0][0]
        den_arr = L.den[0][0]
        num_sym = sp.Poly(num_arr.tolist(), s).as_expr()
        den_sym = sp.Poly(den_arr.tolist(), s).as_expr()
        # s^power * L(s) = s^power * num / den
        expr = sp.cancel((s**power * num_sym) / den_sym)
        # Evaluate at s=0
        val = expr.subs(s, 0)
        # If still symbolic (e.g. still has s), take limit
        if val.free_symbols:
            val = sp.limit(expr, s, 0)
        # Sympy infinity → Python float inf
        if getattr(val, 'is_infinite', False) or val in (sp.oo, sp.zoo, -sp.oo):
            return float('inf')
        f = float(val)
        return f
    except Exception:
        return float('nan')


def _ess_step(sys_type: int, Kp: float) -> float:
    if sys_type >= 1:
        return 0.0
    if np.isinf(Kp):
        return 0.0
    if abs(Kp) < 1e-12:
        return 1.0
    if abs(1.0 + Kp) < 1e-12:
        return float('inf')
    return 1.0 / (1.0 + Kp)


def _ess_ramp(sys_type: int, Kv: float) -> float:
    if sys_type >= 2:
        return 0.0
    if sys_type == 0:
        return float('inf')
    if np.isinf(Kv):
        return 0.0
    if abs(Kv) < 1e-12:
        return float('inf')
    return 1.0 / Kv


def _ess_parabola(sys_type: int, Ka: float) -> float:
    if sys_type >= 3:
        return 0.0
    if sys_type <= 1:
        return float('inf')
    if np.isinf(Ka):
        return 0.0
    if abs(Ka) < 1e-12:
        return float('inf')
    return 1.0 / Ka


def _dc_sensitivity(
    L: ctl.TransferFunction,
    T: ctl.TransferFunction | None,
) -> tuple[float, float]:
    """Evaluate |S(0)| and |T(0)|."""
    try:
        num_L = float(np.polyval(L.num[0][0], 0))
        den_L = float(np.polyval(L.den[0][0], 0))
        if abs(den_L) < 1e-12:
            # Integrator in loop → S(0) ≈ 0
            return 0.0, 1.0
        L0 = num_L / den_L
        if abs(1.0 + L0) < 1e-12:
            return float('inf'), float('inf')
        S0 = abs(1.0 / (1.0 + L0))
        T0 = abs(L0 / (1.0 + L0))
        return float(S0), float(T0)
    except Exception:
        return float('nan'), float('nan')


def _fmt(v: float) -> str:
    if np.isnan(v):   return "N/A"
    if np.isinf(v):   return "∞"
    return f"{v:.4g}"


# ──────────────────────────────────────────────────────────────
#  Bode–Freudenberg: the waterbed (ch.7, slides 18–19/20)
# ──────────────────────────────────────────────────────────────

@dataclass
class WaterbedResult:
    """
    The sensitivity integral constraint.

    For a loop with relative degree ≥ 2 and open-loop RHP poles ``p_k``,

        ∫₀^∞ ln|S(jω)| dω = π · Σ Re(p_k)

    which is **zero** when the plant is stable. Sensitivity reduction in one
    band is therefore paid for by amplification in another: pushing |S| down
    at low frequency pushes it up somewhere else. Hence "waterbed".
    """
    integral:     float       # ∫ ln|S| dω, computed numerically
    theoretical:  float       # π · Σ Re(p_k) over open-loop RHP poles
    rhp_poles:    list        # the poles that set the budget
    area_above:   float       # ∫ max(ln|S|, 0) dω — the amplified part
    area_below:   float       # ∫ min(ln|S|, 0) dω — the attenuated part
    Ms:           float       # peak |S|
    w_Ms:         float
    relative_degree: int
    applies:      bool        # preconditions of the theorem are met
    closed_loop_stable: bool = True
    note:         str = ""

    def summary(self) -> str:
        if not self.applies:
            return f"Bode–Freudenberg does not apply here. {self.note}"
        lines = [
            f"∫ ln|S| dω = {self.integral:.4g}   "
            f"(theory: π·Σ Re(pₖ) = {self.theoretical:.4g})",
            f"  amplified  (|S|>1): +{self.area_above:.4g}",
            f"  attenuated (|S|<1): {self.area_below:.4g}",
            f"  peak Ms = {self.Ms:.4g} at ω = {self.w_Ms:.4g} rad/s",
        ]
        if self.rhp_poles:
            poles = ", ".join(f"{p.real:.4g}" for p in self.rhp_poles)
            lines.append(f"  RHP pole(s) at {poles} raise the budget above 0: "
                         f"amplification is unavoidable.")
        else:
            lines.append("  Budget is 0: every dB of attenuation is paid for "
                         "by amplification elsewhere.")
        return "\n".join(lines)


def _waterbed_grid(scale: float, relative_degree: int) -> np.ndarray:
    """
    Frequency grid for the sensitivity integral.

    The integral is over ``dω``, not ``d(log ω)``, so the high-frequency tail
    carries real weight. How far it must be followed depends on relative
    degree: ``ln|S| ~ O(ω^-r)``, so a relative degree of 2 has a tail decaying
    only as ``1/ω²`` and needs several more decades than a relative degree of
    3 before it is negligible.

    A dense linear grid covers the region where the dynamics are, and a
    geometric grid carries the tail out cheaply. ``np.trapezoid`` handles the
    non-uniform spacing.
    """
    lo = 1e-3 * scale
    hi = 40.0 * scale

    # Low end: a loop with integrators has S(0) = 0, so ln|S| → −∞ as ω → 0.
    # The singularity is integrable (∫₀^δ ln ω dω → 0), but on a uniform grid
    # the first interval alone contributes a spurious −4e-3 — enough to swamp
    # the result for a stable plant, whose true integral is exactly 0. ln|S| is
    # near-linear in log ω there, so a geometric grid resolves it cleanly.
    head = np.geomspace(1e-12 * scale, lo, 8000)
    near = np.linspace(lo, hi, 60000)
    # High end: ln|S| ~ O(ω^-r), so a low relative degree needs more decades
    # before the tail is negligible.
    decades = 7 if relative_degree <= 2 else 4
    tail = np.geomspace(hi, hi * 10 ** decades, 40000)
    return np.unique(np.concatenate([head, near, tail]))


def waterbed(loop_tf: ctl.TransferFunction,
             sensitivity_tf: ctl.TransferFunction | None = None,
             omega: np.ndarray | None = None) -> WaterbedResult:
    """
    Evaluate the Bode sensitivity integral for a loop.

    The numerical integral is taken over a wide frequency grid; it converges
    only when ``|S| → 1`` at high frequency, which is why relative degree ≥ 2
    is required. Where the theorem does not apply, ``applies`` is False and the
    integral is reported for information only.
    """
    from .freqresp import response

    poles = np.atleast_1d(ctl.poles(loop_tf))
    zeros = np.atleast_1d(ctl.zeros(loop_tf))
    relative_degree = len(poles) - len(zeros)
    rhp = [complex(p) for p in poles if p.real > 1e-9]
    theoretical = float(np.pi * sum(p.real for p in rhp))

    if sensitivity_tf is None:
        sensitivity_tf = ctl.feedback(ctl.TransferFunction([1], [1]), loop_tf)

    if omega is None:
        scale = max([abs(p) for p in poles] + [abs(z) for z in zeros] + [1.0])
        omega = _waterbed_grid(scale, relative_degree)

    mag, _ = response(sensitivity_tf, omega)
    ln_S = np.log(np.maximum(mag, 1e-300))

    integral = float(np.trapezoid(ln_S, omega))
    area_above = float(np.trapezoid(np.maximum(ln_S, 0.0), omega))
    area_below = float(np.trapezoid(np.minimum(ln_S, 0.0), omega))

    peak = int(np.argmax(mag))

    # The theorem assumes the closed loop is stable — it is a statement about
    # how a *working* loop must distribute its sensitivity, not a law that
    # holds for any L. Without this check an unstable closed loop returns a
    # number that looks like a violation of the theorem rather than a system
    # outside its hypotheses.
    cl_poles = np.atleast_1d(ctl.poles(sensitivity_tf))
    closed_loop_stable = bool(len(cl_poles) == 0
                              or all(p.real < 0 for p in cl_poles))

    note = ""
    applies = True
    if not closed_loop_stable:
        applies = False
        note = ("The closed loop is unstable, so |S| does not decay and the "
                "integral has no meaning here. Stabilise the loop first.")
    elif relative_degree < 2:
        applies = False
        note = (f"Relative degree is {relative_degree}; the theorem needs ≥ 2 "
                f"for |S| to approach 1 fast enough for the integral to "
                f"converge.")

    return WaterbedResult(
        integral=integral, theoretical=theoretical, rhp_poles=rhp,
        area_above=area_above, area_below=area_below,
        Ms=float(mag[peak]), w_Ms=float(omega[peak]),
        relative_degree=relative_degree,
        applies=applies, closed_loop_stable=closed_loop_stable, note=note,
    )

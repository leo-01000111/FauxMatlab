"""
Controller design and tuning (ch.8 of the course).
===================================================
Builds PID, PI, PD, lead, lag controllers as python-control TFs.
Implements Ziegler-Nichols rules (step-response method and
ultimate-gain method).  Also supports lead/lag compensator design
from desired phase-margin specifications.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import control as ctl
import numpy as np

# ──────────────────────────────────────────────────────────────
#  Enumerations
# ──────────────────────────────────────────────────────────────

class ControllerType(str, Enum):
    P       = "P"
    PI      = "PI"
    PD      = "PD"
    PID     = "PID"
    LEAD    = "Lead"
    LAG     = "Lag"
    LEADLAG = "Lead-Lag"
    CUSTOM  = "Custom"


# ──────────────────────────────────────────────────────────────
#  Controller parameter dataclasses
# ──────────────────────────────────────────────────────────────

@dataclass
class PIDParams:
    Kp: float = 1.0
    Ki: float = 0.0
    Kd: float = 0.0
    Tf: float = 0.0    # derivative filter time constant (0 = ideal)
    # Derived: Ti = Kp/Ki, Td = Kd/Kp (standard notation)

    @property
    def Ti(self) -> float:
        return (self.Kp / self.Ki) if abs(self.Ki) > 1e-12 else float('inf')

    @property
    def Td(self) -> float:
        return (self.Kd / self.Kp) if abs(self.Kp) > 1e-12 else 0.0


@dataclass
class LeadLagParams:
    """
    Parameters of ``C(s) = K·(τs + 1)/(ατs + 1)``.

    The single convention used everywhere: the zero is at ``1/τ`` and the pole
    at ``1/(ατ)``.  So **α < 1 is a lead** (pole above the zero, phase added)
    and **α > 1 is a lag** (pole below the zero, low-frequency gain added).

    v1's default was ``alpha=10.0`` with ``is_lead=True``, a combination
    ``lead_tf`` rejects — so constructing the dataclass with its own defaults
    and passing it to its own builder raised. The docstring there also stated
    the convention backwards relative to the check it performed.
    """
    K:       float = 1.0    # static gain
    alpha:   float = 0.1    # α < 1 → lead;  α > 1 → lag
    tau:     float = 1.0    # zero at 1/τ, pole at 1/(ατ)
    is_lead: bool  = True

    def __post_init__(self) -> None:
        if self.alpha <= 0:
            raise ValueError(f"alpha must be positive, got {self.alpha}")
        if self.tau <= 0:
            raise ValueError(f"tau must be positive, got {self.tau}")
        if self.is_lead and self.alpha >= 1.0:
            raise ValueError(
                f"a lead compensator needs alpha < 1 (got {self.alpha}); "
                f"set is_lead=False for a lag"
            )
        if not self.is_lead and self.alpha <= 1.0:
            raise ValueError(
                f"a lag compensator needs alpha > 1 (got {self.alpha}); "
                f"set is_lead=True for a lead"
            )

    @property
    def max_phase_deg(self) -> float:
        """Peak phase contribution, ``arcsin((1−α)/(1+α))`` — negative for a lag."""
        a = self.alpha
        return float(np.degrees(np.arcsin((1.0 - a) / (1.0 + a))))

    @property
    def w_max_phase(self) -> float:
        """Frequency of that peak, the geometric mean of zero and pole."""
        return float(1.0 / (self.tau * np.sqrt(self.alpha)))


# ──────────────────────────────────────────────────────────────
#  Controller TF builders
# ──────────────────────────────────────────────────────────────

def pid_tf(params: PIDParams) -> ctl.TransferFunction:
    """
    Build the PID transfer function.
    Ideal:    K(s) = Kp + Ki/s + Kd·s
    Practical: K(s) = Kp + Ki/s + Kd·s / (Tf·s + 1)   (filtered derivative)
    """
    Kp, Ki, Kd, Tf = params.Kp, params.Ki, params.Kd, params.Tf

    if abs(Tf) < 1e-12:
        # Ideal PID: (Kd·s² + Kp·s + Ki) / s
        if abs(Ki) < 1e-12 and abs(Kd) < 1e-12:
            return ctl.TransferFunction([Kp], [1])  # pure P
        if abs(Kd) < 1e-12:
            # PI: (Kp·s + Ki) / s
            return ctl.TransferFunction([Kp, Ki], [1, 0])
        if abs(Ki) < 1e-12:
            # PD: Kp + Kd·s = (Kd·s + Kp) / 1
            return ctl.TransferFunction([Kd, Kp], [1])
        # Full PID: (Kd·s² + Kp·s + Ki) / s
        return ctl.TransferFunction([Kd, Kp, Ki], [1, 0])
    else:
        # Practical PID with filtered derivative
        # K(s) = Kp + Ki/s + Kd·s/(Tf·s+1)
        # Common denominator: s·(Tf·s+1)
        # = [Kp·s·(Tf·s+1) + Ki·(Tf·s+1) + Kd·s²] / [s·(Tf·s+1)]
        # Numerator: (Kp·Tf + Kd)·s² + (Kp + Ki·Tf)·s + Ki
        # Denominator: Tf·s² + s
        if abs(Ki) < 1e-12:
            # PD with filter: (Kd·s + Kp)/(Tf·s+1)
            return ctl.TransferFunction([Kd, Kp], [Tf, 1])
        num = [Kp * Tf + Kd, Kp + Ki * Tf, Ki]
        den = [Tf, 1, 0]
        return ctl.TransferFunction(num, den)


def leadlag_tf(params: LeadLagParams) -> ctl.TransferFunction:
    """
    ``C(s) = K·(τs + 1)/(ατs + 1)`` — lead or lag, decided by ``α``.

    Prefer this over :func:`lead_tf` / :func:`lag_tf`: it cannot be called with
    the wrong one.
    """
    tau, alpha, K = params.tau, params.alpha, params.K
    return ctl.TransferFunction([K * tau, K], [alpha * tau, 1.0])


def lead_tf(params: LeadLagParams) -> ctl.TransferFunction:
    """
    Lead compensator (ch.8, slide 30/44), a PD approximation.

    ``C(s) = K·(τs + 1)/(ατs + 1)`` with ``α < 1``: the zero at ``1/τ`` sits
    below the pole at ``1/(ατ)``, so phase is *added* around
    ``ω = 1/(τ√α)``, peaking at ``arcsin((1−α)/(1+α))``. Used to raise the
    phase margin without the unbounded high-frequency gain of a pure PD.
    """
    if params.alpha >= 1.0:
        raise ValueError(
            f"a lead compensator needs alpha < 1 (got {params.alpha}): the "
            f"zero 1/τ must sit below the pole 1/(ατ). Use lag_tf for α > 1."
        )
    return leadlag_tf(params)


def lag_tf(params: LeadLagParams) -> ctl.TransferFunction:
    """
    Lag compensator (ch.8, slide 33/44), a PI approximation.

    ``C(s) = K·(τs + 1)/(ατs + 1)`` with ``α > 1``: raises low-frequency gain
    (better steady-state accuracy) while leaving the phase near crossover
    almost untouched, unlike a pure integrator which costs a full 90°.
    """
    if params.alpha <= 1.0:
        raise ValueError(
            f"a lag compensator needs alpha > 1 (got {params.alpha}). "
            f"Use lead_tf for α < 1."
        )
    return leadlag_tf(params)


def lead_design(
    G: ctl.TransferFunction,
    desired_pm_deg: float = 60.0,
    desired_wc:     float | None = None,
) -> tuple[LeadLagParams, ctl.TransferFunction]:
    """
    Design a lead compensator to achieve desired_pm_deg.
    If desired_wc is given, places the compensator peak there.
    Returns (params, tf).
    """
    from .freqresp import bode as _bode

    bd = _bode(G)
    current_pm = bd.pm_deg
    current_wc = bd.wc

    if not np.isfinite(current_pm):
        current_pm = 0.0
    additional_phase = desired_pm_deg - current_pm + 10.0   # 10° safety margin
    # arcsin saturates at α → 0, so a single lead section cannot exceed ~70°.
    additional_phase = float(np.clip(additional_phase, 0.0, 70.0))

    # α from the desired phase boost: sin(φ_max) = (1−α)/(1+α)
    sin_phi = np.sin(np.radians(additional_phase))
    alpha = float(np.clip((1.0 - sin_phi) / (1.0 + sin_phi), 1e-4, 0.999))

    wc_target = desired_wc if desired_wc is not None else current_wc
    if wc_target is None or not np.isfinite(wc_target) or wc_target <= 0:
        wc_target = 1.0

    tau = 1.0 / (wc_target * np.sqrt(alpha))

    # Choose K so the compensated loop crosses 0 dB exactly at wc_target.
    from .freqresp import response as _response
    w = np.array([wc_target])
    mag_G, _ = _response(G, w)
    mag_C, _ = _response(ctl.TransferFunction([tau, 1.0], [alpha * tau, 1.0]), w)
    product = float(mag_G[0]) * float(mag_C[0])
    K = 1.0 / product if product > 1e-12 else 1.0

    params = LeadLagParams(K=K, alpha=alpha, tau=tau, is_lead=True)
    return params, lead_tf(params)


# ──────────────────────────────────────────────────────────────
#  Ziegler–Nichols (ch.8)
# ──────────────────────────────────────────────────────────────

@dataclass
class ZNStepResult:
    """ZN from step-response method (reaction-curve method)."""
    L:  float    # apparent dead time (lag)
    T:  float    # time constant
    a:  float    # slope = T / (L·dc_gain) ~ reaction rate
    dc_gain: float
    # ZN tuning rules
    P_params:   PIDParams
    PI_params:  PIDParams
    PID_params: PIDParams


@dataclass
class ZNUltimateResult:
    """ZN from ultimate-gain method."""
    Ku: float    # ultimate gain
    Tu: float    # ultimate period (s)
    wu: float    # ultimate frequency (rad/s)
    P_params:   PIDParams
    PI_params:  PIDParams
    PID_params: PIDParams


def zn_step(
    G: ctl.TransferFunction,
    amplitude: float = 1.0,
) -> ZNStepResult:
    """
    Ziegler–Nichols reaction-curve method.
    Estimates dead time L and time constant T from the open-loop step response.
    Uses the tangent-at-inflection-point method.
    """
    import numpy as np

    from .timeresp import _auto_tspan, step_response

    t = _auto_tspan(G, n_pts=4000)
    resp = step_response(G, amplitude=amplitude, t=t)
    y = resp.y.ravel()
    t_arr = resp.t

    # DC gain
    dc = float(np.mean(y[int(0.9 * len(y)):]))
    if abs(dc) < 1e-12:
        raise ValueError("DC gain is ~0; ZN reaction-curve cannot be applied.")

    # Normalise to unit step
    y_norm = y / (dc / amplitude)

    # Inflection point = maximum slope of the normalised reaction curve.
    dy = np.gradient(y_norm, t_arr)
    idx = int(np.argmax(dy))
    slope = float(dy[idx])
    if abs(slope) < 1e-12:
        raise ValueError("Slope at the inflection point is ~0; cannot apply Z-N.")

    # The tangent at the inflection point cuts y = 0 at t = L (apparent dead
    # time) and y = 1 at t = L + T (apparent time constant).
    L = float(t_arr[idx] - y_norm[idx] / slope)
    T = float(1.0 / slope)
    L = max(L, 0.0)
    if L < 1e-9:
        raise ValueError(
            "Apparent dead time L ≈ 0, so the reaction-curve method gives "
            "infinite gains. It is meant for processes with transport delay — "
            "add a Padé delay block, or use the ultimate-gain method instead."
        )

    # ZN rules
    P_params   = PIDParams(Kp=T / (dc * L))
    PI_params  = PIDParams(Kp=0.9 * T / (dc * L),
                           Ki=0.9 * T / (dc * L) / (3.33 * L))
    PID_params = PIDParams(Kp=1.2 * T / (dc * L),
                           Ki=1.2 * T / (dc * L) / (2.0 * L),
                           Kd=1.2 * T / (dc * L) * 0.5 * L)

    return ZNStepResult(
        L=L, T=T, a=slope, dc_gain=float(dc / amplitude),
        P_params=P_params, PI_params=PI_params, PID_params=PID_params,
    )


def zn_ultimate(
    G: ctl.TransferFunction,
    K2: ctl.TransferFunction | None = None,
) -> ZNUltimateResult:
    """
    Ziegler–Nichols oscillation method (ch.8, slide 37/44).

    Raises proportional gain until the loop oscillates steadily: ``K_u`` is
    that ultimate gain and ``T_u`` the oscillation period. Found exactly by
    :func:`fakematlab.core.stability.marginal_gain`, which solves for the
    imaginary-axis crossing of ``1 + K·L(s)`` algebraically.

    v1 scanned a root locus for a sign change instead; its branch tracking was
    broken, so this raised "Could not find ultimate gain" for every system.
    """
    from .stability import marginal_gain

    L = G if K2 is None else K2 * G
    result = marginal_gain(L)

    if result is None:
        order_excess = len(np.atleast_1d(ctl.poles(L))) - \
                       len(np.atleast_1d(ctl.zeros(L)))
        hint = ("Loops of relative degree 1 or 2 with no right-half-plane "
                "poles never cross the imaginary axis — no proportional gain "
                "destabilises them, so there is no ultimate gain to find."
                if order_excess <= 2 else
                "Try the reaction-curve method instead.")
        raise ValueError(
            f"This loop has no ultimate gain: the root locus never crosses "
            f"the imaginary axis for K > 0. {hint}"
        )

    Ku, wu = result
    Tu = 2 * np.pi / wu if wu > 0 else float("inf")

    P_params   = PIDParams(Kp=0.5  * Ku)
    PI_params  = PIDParams(Kp=0.45 * Ku,
                           Ki=0.45 * Ku / (0.833 * Tu))
    PID_params = PIDParams(Kp=0.6  * Ku,
                           Ki=0.6  * Ku / (0.5 * Tu),
                           Kd=0.6  * Ku * 0.125 * Tu)

    return ZNUltimateResult(
        Ku=Ku, Tu=Tu, wu=wu,
        P_params=P_params, PI_params=PI_params, PID_params=PID_params,
    )

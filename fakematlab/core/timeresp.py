"""
Time-domain response computation and metrics.
=============================================
Step, impulse, ramp responses with full ch.3 metric extraction:
Mp, tp, ts (±2% and ±5%), tr (10–90% and 0–100%), Mu, y_inf, DC gain.
Also supports parameter sweeps for multi-curve overlay plots.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import control as ctl
import numpy as np

# ──────────────────────────────────────────────────────────────
#  Result dataclasses
# ──────────────────────────────────────────────────────────────

@dataclass
class TimeResponse:
    """Raw time-response data from one simulation."""
    t:          np.ndarray   # time vector
    y:          np.ndarray   # output (may be multi-row for multi-output)
    label:      str = ""
    input_type: str = "step"  # "step", "impulse", "ramp", "initial"
    amplitude:  float = 1.0
    metadata:   dict = field(default_factory=dict)


@dataclass
class StepMetrics:
    """
    Standard step-response metrics (ch.3 slide 19–21, ch.7).
    All times in seconds; undefined values are NaN.
    """
    y_inf:       float    # DC gain / steady-state value
    dc_gain:     float    # = y_inf for unit step
    Mp_pct:      float    # percent overshoot  (nan if no overshoot)
    tp:          float    # peak time           (nan if monotone)
    Mu_abs:      float    # absolute undershoot (nan if none)
    tr_1090:     float    # 10% → 90% rise time (nan if non-monotone)
    tr_0100:     float    # 0% → 100% rise time (first crossing)
    ts_2pct:     float    # settling time ±2%
    ts_5pct:     float    # settling time ±5%
    y_max:       float    # absolute peak value
    steady_state_error: float  # 1 − y_inf  (for unit step)

    def as_dict(self) -> dict[str, float]:
        return {
            "y∞ (steady state)":     self.y_inf,
            "DC gain":               self.dc_gain,
            "Overshoot Mp (%)":      self.Mp_pct,
            "Peak time tp (s)":      self.tp,
            "Undershoot Mu":         self.Mu_abs,
            "Rise time tr 10–90%":   self.tr_1090,
            "Rise time tr 0–100%":   self.tr_0100,
            "Settling time ts ±2%":  self.ts_2pct,
            "Settling time ts ±5%":  self.ts_5pct,
            "Steady-state error":    self.steady_state_error,
        }


# ──────────────────────────────────────────────────────────────
#  Response computation
# ──────────────────────────────────────────────────────────────

def _auto_tspan(tf: ctl.TransferFunction, n_pts: int = 2000) -> np.ndarray:
    """
    A time window that actually frames the transient.

    The span is driven by the **settling time** of the slowest stable mode:
    a pole at ``−σ`` decays as ``e^{−σt}``, so it is within 2% of its final
    value after roughly ``4/σ``. Showing ``~1.4×`` that puts the interesting
    part across the plot with a little steady state for context.

    v1 used ``50/σ`` — twelve times the settling time — so a pole at −1 gave a
    50 s window and squeezed the whole response into the leftmost 5% of the
    axis. That is what every screenshot of the Time tab looked like.

    Oscillatory and unstable systems are handled separately: for a lightly
    damped pair the envelope, not the real part, sets the useful window, and
    an unstable system is shown for a few time constants of its growth before
    the axis becomes useless.
    """
    poles = np.atleast_1d(ctl.poles(tf))
    if len(poles) == 0:
        return np.linspace(0.0, 10.0, n_pts)

    stable = [p for p in poles if p.real < -1e-9]
    unstable = [p for p in poles if p.real > 1e-9]
    integrators = [p for p in poles if abs(p.real) <= 1e-9]

    if unstable:
        # Show a handful of doubling times of the fastest-growing mode.
        growth = max(p.real for p in unstable)
        t_end = 7.0 / growth
    elif stable:
        slowest = min(abs(p.real) for p in stable)
        t_end = 5.5 / slowest                       # ≈ 1.4 × the ±2% settling time
        # A lightly damped pair needs enough room for a few oscillations.
        osc = [abs(p.imag) for p in stable if abs(p.imag) > 1e-9]
        if osc:
            # Enough room for a few cycles of the slowest oscillation, but not
            # so many that the decaying envelope leaves a flat tail dominating
            # the axis.
            slowest_period = 2.0 * np.pi / max(min(osc), 1e-9)
            t_end = max(t_end, 3.5 * slowest_period)
    elif integrators:
        t_end = 20.0                                # pure integrator: ramp away
    else:
        t_end = 10.0

    t_end = float(np.clip(t_end, 1e-3, 1000.0))
    return np.linspace(0.0, t_end, n_pts)


def step_response(
    tf: ctl.TransferFunction,
    amplitude: float = 1.0,
    t: np.ndarray | None = None,
    label: str = "",
) -> TimeResponse:
    """
    Step response scaled by ``amplitude``.

    For a stable system the exact steady-state value ``amplitude·G(0)`` is
    recorded in ``metadata['y_inf_exact']`` so that
    :func:`compute_step_metrics` need not estimate it from the tail of the
    simulation — see that function for why the estimate biases every metric.
    """
    if t is None:
        t = _auto_tspan(tf)
    t_out, y_out = ctl.step_response(tf, T=t)

    meta: dict[str, Any] = {}
    poles = np.atleast_1d(ctl.poles(tf))
    if len(poles) and all(p.real < -1e-12 for p in poles):
        from .tf_utils import dc_gain
        gain = dc_gain(tf)
        if np.isfinite(gain):
            meta["y_inf_exact"] = float(gain) * amplitude

    return TimeResponse(
        t=t_out, y=y_out * amplitude,
        label=label or "step", input_type="step", amplitude=amplitude,
        metadata=meta,
    )


def impulse_response(
    tf: ctl.TransferFunction,
    amplitude: float = 1.0,
    t: np.ndarray | None = None,
    label: str = "",
) -> TimeResponse:
    """Compute impulse response scaled by amplitude."""
    if t is None:
        t = _auto_tspan(tf)
    t_out, y_out = ctl.impulse_response(tf, T=t)
    return TimeResponse(
        t=t_out, y=y_out * amplitude,
        label=label or "impulse", input_type="impulse", amplitude=amplitude,
    )


def ramp_response(
    tf: ctl.TransferFunction,
    slope: float = 1.0,
    t: np.ndarray | None = None,
    label: str = "",
) -> TimeResponse:
    """
    Compute ramp response y(t) for input u(t) = slope·t.
    Implemented via step response of tf/s.
    """
    if t is None:
        t = _auto_tspan(tf)
    # Integrate: ramp = step passed through integrator
    tf_int = tf * ctl.TransferFunction([1], [1, 0])
    try:
        t_out, y_out = ctl.step_response(tf_int, T=t)
    except Exception:
        # Fallback: simulate via scipy
        u = slope * t
        resp = _simulate(tf, t, u)
        return TimeResponse(t=t, y=resp, label=label or "ramp",
                            input_type="ramp", amplitude=slope)
    return TimeResponse(
        t=t_out, y=y_out * slope,
        label=label or "ramp", input_type="ramp", amplitude=slope,
    )


def _simulate(tf: ctl.TransferFunction,
              t: np.ndarray, u: np.ndarray) -> np.ndarray:
    """Generic simulation via forced_response."""
    t_out, y_out = ctl.forced_response(tf, T=t, U=u)
    return y_out


# ──────────────────────────────────────────────────────────────
#  Metrics
# ──────────────────────────────────────────────────────────────

def compute_step_metrics(resp: TimeResponse) -> StepMetrics:
    """
    Extract ch.3 step-response metrics from a TimeResponse.
    Works on both stable (converging) and marginally stable responses.
    """
    t = resp.t
    y = np.asarray(resp.y).ravel()
    amp = resp.amplitude

    # --- Steady-state value ---
    # Prefer the exact amplitude·G(0) recorded by step_response(). Estimating
    # y∞ from the tail of a finite simulation biases every metric that depends
    # on it: for 1/(s+1) over a 5.5 s window the tail mean is ~0.9945, which
    # shifts the ±2% band down and reports ts = 3.68 s instead of 3.91 s. The
    # tail mean is kept only for systems with no exact value — marginally
    # stable ones, where it is the best available answer.
    y_inf = resp.metadata.get("y_inf_exact")
    if y_inf is None:
        tail_start = int(0.90 * len(y))
        y_inf = float(np.mean(y[tail_start:])) if tail_start < len(y) \
            else float(y[-1])
    y_inf = float(y_inf)
    dc_gain = y_inf / amp if abs(amp) > 1e-12 else float('nan')

    # --- Overshoot ---
    y_max = float(np.max(y))
    if abs(y_inf) > 1e-12:
        Mp_pct = max(0.0, (y_max - y_inf) / abs(y_inf) * 100.0)
    else:
        Mp_pct = float('nan')

    # --- Peak time ---
    peak_idx = int(np.argmax(y))
    tp = float(t[peak_idx]) if Mp_pct > 0.1 else float('nan')

    # --- Undershoot ---
    y_min = float(np.min(y))
    Mu_abs = abs(y_min) if y_min < 0 else float('nan')

    # --- Rise time tr 0→100% (first crossing of y_inf) ---
    if abs(y_inf) > 1e-12 and not np.isnan(y_inf):
        crossings = np.where(np.diff(np.sign(y - y_inf)))[0]
        tr_0100 = float(t[crossings[0]]) if len(crossings) > 0 else float('nan')
    else:
        tr_0100 = float('nan')

    # --- Rise time tr 10→90% ---
    if abs(y_inf) > 1e-12:
        y10 = 0.10 * y_inf
        y90 = 0.90 * y_inf
        idx10 = _first_crossing(y, y10)
        idx90 = _first_crossing(y, y90)
        if idx10 is not None and idx90 is not None and idx90 > idx10:
            tr_1090 = float(t[idx90] - t[idx10])
        else:
            tr_1090 = float('nan')
    else:
        tr_1090 = float('nan')

    # --- Settling times ±2% and ±5% ---
    ts_2pct = _settling_time(t, y, y_inf, 0.02)
    ts_5pct = _settling_time(t, y, y_inf, 0.05)

    sse = 1.0 * amp - y_inf  # steady-state error for step input = amp

    return StepMetrics(
        y_inf=y_inf, dc_gain=dc_gain,
        Mp_pct=Mp_pct, tp=tp, Mu_abs=Mu_abs,
        tr_1090=tr_1090, tr_0100=tr_0100,
        ts_2pct=ts_2pct, ts_5pct=ts_5pct,
        y_max=y_max,
        steady_state_error=sse,
    )


def _first_crossing(y: np.ndarray, level: float) -> int | None:
    """Index of first sample where y crosses level (from below)."""
    below = y < level
    for i in range(len(below) - 1):
        if below[i] and not below[i + 1]:
            return i + 1
    return None


def _settling_time(t: np.ndarray, y: np.ndarray,
                   y_inf: float, band: float) -> float:
    """
    Time at which y enters ±band·|y_inf| and never leaves.
    Returns t[-1] (last time point) if not settled.
    """
    if abs(y_inf) < 1e-12:
        return float('nan')
    tol = band * abs(y_inf)
    in_band = np.abs(y - y_inf) <= tol
    # Walk backwards from the end to find where it last left the band
    for i in range(len(in_band) - 1, -1, -1):
        if not in_band[i]:
            # y left the band at index i; settled at i+1
            idx = i + 1
            return float(t[idx]) if idx < len(t) else float(t[-1])
    # Never left band → already settled at t[0]
    return float(t[0])


# ──────────────────────────────────────────────────────────────
#  Parameter sweep
# ──────────────────────────────────────────────────────────────

@dataclass
class SweepResult:
    """Collection of responses for different parameter values."""
    responses: list[TimeResponse]
    param_name: str
    param_values: list[float]


def parameter_sweep(
    tf_factory,                 # callable(param_value) → TransferFunction
    param_values: list[float],
    param_name: str = "K",
    response_type: str = "step",
    amplitude: float = 1.0,
    t: np.ndarray | None = None,
) -> SweepResult:
    """
    Compute step/impulse/ramp responses for a list of parameter values.

    tf_factory is a callable that takes a scalar and returns a TF.
    Example:
        sweep = parameter_sweep(
            lambda K: ctl.feedback(K * G, 1),
            param_values=[0.5, 1.0, 2.0, 5.0],
            param_name="K",
        )
    """
    responses = []
    for val in param_values:
        tf = tf_factory(val)
        label = f"{param_name} = {val:g}"
        if response_type == "step":
            resp = step_response(tf, amplitude=amplitude, t=t, label=label)
        elif response_type == "impulse":
            resp = impulse_response(tf, amplitude=amplitude, t=t, label=label)
        elif response_type == "ramp":
            resp = ramp_response(tf, slope=amplitude, t=t, label=label)
        else:
            raise ValueError(f"Unknown response_type '{response_type}'")
        responses.append(resp)
    return SweepResult(responses=responses, param_name=param_name,
                       param_values=param_values)

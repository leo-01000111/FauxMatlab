"""
The MATLAB-shaped namespace.
============================
Every name a course snippet is likely to type, behaving the way MATLAB's
version behaves — including the small things that make transcription work:
``stepinfo`` returns a struct-like mapping with MATLAB's field names,
``margin`` returns ``(Gm, Pm, Wcg, Wcp)`` with ``Gm`` in absolute units,
``damp`` prints a table, and the plotting commands draw instead of returning.

What this is not
----------------
Not a MATLAB interpreter. There is no ``.m`` parser, no ``end`` keyword, no
1-based indexing — the language is Python. The names are a vocabulary, so that
``G = tf([1],[1 2 1])`` needs only its commas added rather than a rewrite.
That was decision D4, taken because a half-working parser is worse than an
honest Python prompt.
"""

from __future__ import annotations

import math
from typing import Any

import control as ctl
import numpy as np

from ..core import discrete as _discrete
from ..core import freqresp as _freq
from ..core import observers as _obs
from ..core import performance as _perf
from ..core import stability as _stab
from ..core import statefbk as _fbk
from ..core import statespace as _ss
from ..core import structural as _struct
from ..core import timeresp as _time
from ..core import tf_utils as _tfu
from .figures import FigureSpec, emit


# ──────────────────────────────────────────────────────────────
#  Construction
# ──────────────────────────────────────────────────────────────

def tf(num, den=None, dt=None):
    """
    Transfer function. ``tf([1], [1, 2, 1])``, or ``tf('s')`` for the variable.

    ``tf('s')`` returns the Laplace variable so an expression can be written
    the way it is written on paper: ``G = 1/(s**2 + 2*s + 1)``.
    """
    if isinstance(num, str):
        if num.strip() == "s":
            return ctl.tf([1, 0], [1])
        if num.strip() == "z":
            return ctl.tf([1, 0], [1], den if den else 1.0)
        raise ValueError(
            f"tf({num!r}) is not understood; use tf('s'), tf('z', Ts), or "
            f"tf(num, den) with coefficient lists")
    if den is None:
        raise ValueError("tf needs a denominator: tf(num, den)")
    return ctl.tf(num, den, dt) if dt else ctl.tf(num, den)


def ss(A, B=None, C=None, D=None, dt=None):
    """State-space model, or a conversion when given one system."""
    if B is None:
        return ctl.tf2ss(A) if isinstance(A, ctl.TransferFunction) else A
    sys = _ss.state_space(A, B, C, D)
    return ctl.sample_system(sys, dt) if dt else sys


def zpk(zeros, poles, gain, dt=None):
    """Zero-pole-gain model."""
    num = np.real(gain * np.poly(zeros)) if len(np.atleast_1d(zeros)) \
        else np.array([float(gain)])
    den = np.real(np.poly(poles)) if len(np.atleast_1d(poles)) \
        else np.array([1.0])
    return ctl.tf(num, den, dt) if dt else ctl.tf(num, den)


def tf2ss(sys):
    return ctl.tf2ss(sys)


def ss2tf(sys):
    return ctl.ss2tf(sys)


# ──────────────────────────────────────────────────────────────
#  Interconnection
# ──────────────────────────────────────────────────────────────

def series(*systems):
    """Cascade. ``series(G, H)`` is ``H·G`` — MATLAB's order, not the product's."""
    result = systems[0]
    for nxt in systems[1:]:
        result = nxt * result
    return result


def parallel(*systems):
    """Sum of systems."""
    result = systems[0]
    for nxt in systems[1:]:
        result = result + nxt
    return result


def feedback(forward, back=1, sign=-1):
    """Closed loop ``forward / (1 ∓ forward·back)``. Negative feedback by default."""
    return ctl.feedback(forward, back, sign=sign)


def minreal(sys, tol=1e-9):
    """
    Minimal realisation.

    Implemented in :mod:`fakematlab.core.statespace` rather than through
    ``control.minreal``, which needs slycot.
    """
    if isinstance(sys, ctl.TransferFunction):
        return ctl.ss2tf(_ss.minimal(ctl.tf2ss(sys), tol))
    return _ss.minimal(sys, tol)


# ──────────────────────────────────────────────────────────────
#  Properties
# ──────────────────────────────────────────────────────────────

def pole(sys):
    return np.atleast_1d(ctl.poles(sys))


def zero(sys):
    return np.atleast_1d(ctl.zeros(sys))


def dcgain(sys):
    return _tfu.dc_gain(sys) if isinstance(sys, ctl.TransferFunction) \
        else float(np.atleast_2d(ctl.dcgain(sys))[0, 0])


class DampTable(tuple):
    """
    ``(wn, zeta, poles)`` that displays as MATLAB's damping table.

    MATLAB decides between printing a table and returning three arrays by
    counting output arguments, which Python cannot see. Returning a tuple
    whose ``repr`` *is* the table gives both behaviours from one call:
    ``damp(G)`` shows the table, ``wn, z, p = damp(G)`` unpacks it.
    """

    def __repr__(self) -> str:
        wn, zeta, poles = self
        rows = [f"{'Pole':>24s} {'Damping':>10s} {'Frequency':>12s} "
                f"{'Time Constant':>15s}",
                f"{'':>24s} {'':>10s} {'(rad/s)':>12s} {'(s)':>15s}"]
        for p, z, w in zip(poles, zeta, wn):
            tau = 1.0 / abs(p.real) if abs(p.real) > 1e-12 else math.inf
            rows.append(f"{_fmt_complex(p):>24s} {z:>10.4g} {w:>12.4g} "
                        f"{tau:>15.4g}")
        return "\n".join(rows)


def damp(sys):
    """Poles with their damping ratio, natural frequency and time constant."""
    poles = np.atleast_1d(ctl.poles(sys))
    wn = np.abs(poles)
    zeta = np.where(wn > 1e-12, -np.real(poles) / np.maximum(wn, 1e-300), 1.0)
    return DampTable((wn, zeta, poles))


def stepinfo(sys, t=None, **kwargs) -> dict[str, float]:
    """
    Step-response metrics, with MATLAB's field names.

    Accepts a system or a ``(t, y)`` pair, and returns a mapping whose keys
    are ``RiseTime``, ``SettlingTime``, ``Overshoot`` … so a snippet reading
    ``info.SettlingTime`` needs only ``info['SettlingTime']``.
    """
    if isinstance(sys, tuple) and len(sys) == 2:
        time_vector, y = sys
        response = _time.TimeResponse(t=np.asarray(time_vector),
                                      y=np.asarray(y), input_type="step")
    else:
        response = _time.step_response(sys, t=t)
    m = _time.compute_step_metrics(response)
    return {
        "RiseTime": m.tr_1090,
        "TransientTime": m.ts_2pct,
        "SettlingTime": m.ts_2pct,
        "SettlingMin": float(np.min(response.y)),
        "SettlingMax": m.y_max,
        "Overshoot": m.Mp_pct,
        "Undershoot": 0.0 if np.isnan(m.Mu_abs) else m.Mu_abs,
        "Peak": m.y_max,
        "PeakTime": m.tp,
        "SteadyState": m.y_inf,
    }


def margin(sys):
    """
    ``(Gm, Pm, Wcg, Wcp)`` — MATLAB's order, with ``Gm`` in absolute units.

    Note the field order: the gain margin's frequency comes *before* the phase
    margin's, which is the opposite of what the names suggest and a reliable
    source of confusion. ``allmargin`` below returns a labelled mapping.
    """
    gm, pm, _sm, wpc, wgc, _wms = ctl.stability_margins(sys)
    return gm, pm, wpc, wgc


def allmargin(sys) -> dict[str, float]:
    """Every margin, named — including the modulus margin MATLAB omits."""
    pm, gm_dB, w180, wc, sm, wms = _freq.stability_margins(sys)
    return {
        "GainMargin_dB": gm_dB,
        "PhaseMargin_deg": pm,
        "GMFrequency": w180,
        "PMFrequency": wc,
        "ModulusMargin": sm,
        "MMFrequency": wms,
        "DelayMargin": (math.radians(abs(pm)) / wc
                        if np.isfinite(wc) and wc > 0 and np.isfinite(pm)
                        else math.inf),
    }


def bandwidth(sys):
    return _freq.bode(sys).bw_3dB


def routh(sys_or_coeffs, K=None):
    """Routh table. Pass a symbol for ``K`` to keep it free."""
    if hasattr(sys_or_coeffs, "den"):
        return _stab.routh_from_closed_loop(sys_or_coeffs, K_sym=K)
    return _stab.routh_table(sys_or_coeffs, symbol=K)


def jury(sys_or_coeffs):
    """Jury table — the discrete counterpart of Routh."""
    if hasattr(sys_or_coeffs, "den"):
        return _discrete.jury_from_system(sys_or_coeffs)
    return _discrete.jury(sys_or_coeffs)


# ──────────────────────────────────────────────────────────────
#  Time response (plotting)
# ──────────────────────────────────────────────────────────────

class PlotResult(tuple):
    """
    The data a plotting command computed, with a one-line display.

    MATLAB switches between drawing and returning data by counting output
    arguments. Python cannot see that, so the commands always return the data
    *and* draw — but echo a summary rather than two thousand numbers, which is
    what makes ``step(T)`` at a prompt behave the way it should. Unpacking
    still works: ``t, y = step(T)``.
    """

    __slots__ = ()
    _what = "result"

    def __repr__(self) -> str:
        first = self[0]
        try:
            span = f"{float(first[0]):g}…{float(first[-1]):g}"
            return (f"<{self._what}: {len(first)} points over {span}"
                    f"  —  unpack with  a, b = ...>")
        except Exception:                                  # noqa: BLE001
            return f"<{self._what}>"


class _TimeResult(PlotResult):
    __slots__ = ()
    _what = "time response"


class _FreqResult(PlotResult):
    """``(magnitude, phase, omega)`` — the span quoted is the frequency one."""

    __slots__ = ()
    _what = "frequency response"

    def __repr__(self) -> str:
        omega = self[2]
        return (f"<frequency response: {len(omega)} points over "
                f"ω = {float(omega[0]):g}…{float(omega[-1]):g} rad/s"
                f"  —  unpack with  mag, phase, w = ...>")


class _PlotPair(tuple):
    """A pair of arrays with a named one-line display."""

    def __new__(cls, values, what: str):
        obj = super().__new__(cls, values)
        obj._what = what
        return obj

    def __repr__(self) -> str:
        return f"<{self._what}: {len(self[1])} gains  —  unpack with a, b = ...>"


def step(*systems, t=None, plot: bool = True):
    """Step response. Plots by default; returns ``(t, y)``."""
    spec = FigureSpec("time", "Step Response", "Time (s)", "Amplitude")
    out = []
    for i, sys in enumerate(systems):
        response = _time.step_response(sys, t=t)
        y = np.asarray(response.y).ravel()
        spec.add(response.t, y, _name(sys, i))
        out.append((response.t, y))
    if plot:
        emit(spec)
    return _TimeResult(out[0]) if len(out) == 1 else out


def impulse(*systems, t=None, plot: bool = True):
    """Impulse response."""
    spec = FigureSpec("time", "Impulse Response", "Time (s)", "Amplitude")
    out = []
    for i, sys in enumerate(systems):
        response = _time.impulse_response(sys, t=t)
        y = np.asarray(response.y).ravel()
        spec.add(response.t, y, _name(sys, i))
        out.append((response.t, y))
    if plot:
        emit(spec)
    return _TimeResult(out[0]) if len(out) == 1 else out


def lsim(sys, u, t, x0=None, plot: bool = True):
    """Response to an arbitrary input."""
    t = np.asarray(t, dtype=float)
    u = np.asarray(u, dtype=float)
    t_out, y = ctl.forced_response(sys, T=t, U=u, X0=x0)[:2]
    y = np.asarray(y).ravel()
    if plot:
        spec = FigureSpec("time", "Response to input", "Time (s)", "Amplitude")
        spec.add(t_out, y, "y")
        spec.add(t_out, np.resize(u, len(t_out)), "u", style="dashed")
        emit(spec)
    return _TimeResult((t_out, y))


def initial(sys, x0, t=None, plot: bool = True):
    """Free response from an initial state."""
    if t is None:
        t = np.linspace(0, 10, 500)
    t_out, y = ctl.initial_response(sys, T=t, X0=x0)[:2]
    y = np.atleast_2d(np.asarray(y))
    if plot:
        spec = FigureSpec("time", "Initial-condition response",
                          "Time (s)", "Amplitude")
        for i, row in enumerate(y):
            spec.add(t_out, row, f"y{i}" if y.shape[0] > 1 else "y")
        emit(spec)
    return _TimeResult((t_out, y[0] if y.shape[0] == 1 else y))


def ramp(sys, t=None, slope: float = 1.0, plot: bool = True):
    """Ramp response — not in MATLAB, but the course asks for it constantly."""
    response = _time.ramp_response(sys, slope=slope, t=t)
    y = np.asarray(response.y).ravel()
    if plot:
        spec = FigureSpec("time", "Ramp Response", "Time (s)", "Amplitude")
        spec.add(response.t, y, "y")
        spec.add(response.t, slope * response.t, "input", style="dashed")
        emit(spec)
    return _TimeResult((response.t, y))


# ──────────────────────────────────────────────────────────────
#  Frequency response (plotting)
# ──────────────────────────────────────────────────────────────

def bode(*systems, w=None, plot: bool = True):
    """Bode magnitude and phase. Returns ``(mag, phase_deg, omega)``."""
    spec = FigureSpec("bode", "Bode Diagram", "ω (rad/s)", "")
    out = []
    for i, sys in enumerate(systems):
        data = _freq.bode(sys, omega=w)
        spec.add(data.omega, data.mag_dB, _name(sys, i))
        spec.extra.setdefault("phase", []).append(
            (data.omega, data.phase_deg, _name(sys, i)))
        spec.extra.setdefault("margins", []).append(
            {"wc": data.wc, "w180": data.w180,
             "gm_dB": data.gm_dB, "pm_deg": data.pm_deg})
        out.append((10 ** (data.mag_dB / 20), data.phase_deg, data.omega))
    if plot:
        emit(spec)
    return _FreqResult(out[0]) if len(out) == 1 else out


def nyquist(*systems, w=None, plot: bool = True):
    """Nyquist diagram, with the −1 point and the encirclement count."""
    spec = FigureSpec("nyquist", "Nyquist Diagram", "Re", "Im")
    out = []
    for i, sys in enumerate(systems):
        data = _freq.nyquist(sys, omega=w)
        spec.add(data.H_pos.real, data.H_pos.imag, _name(sys, i))
        spec.add(data.H_neg.real, data.H_neg.imag, "", style="dashed")
        spec.extra.setdefault("counts", []).append(
            {"N": data.encirclements, "P": data.P, "Z": data.Z})
        out.append(data)
    if plot:
        emit(spec)
    return out[0] if len(out) == 1 else out


def nichols(*systems, w=None, plot: bool = True):
    """Nichols chart."""
    spec = FigureSpec("xy", "Nichols Chart", "Phase (°)", "|L| (dB)")
    out = []
    for i, sys in enumerate(systems):
        data = _freq.nichols(sys, omega=w)
        spec.add(data.phase_deg, data.mag_dB, _name(sys, i))
        out.append(data)
    if plot:
        emit(spec)
    return out[0] if len(out) == 1 else out


def pzmap(*systems, plot: bool = True):
    """Pole-zero map."""
    spec = FigureSpec("pzmap", "Pole-Zero Map", "Re", "Im")
    for i, sys in enumerate(systems):
        poles = np.atleast_1d(ctl.poles(sys))
        zeros = np.atleast_1d(ctl.zeros(sys))
        spec.add(poles.real, poles.imag, f"poles {_name(sys, i)}",
                 style="scatter")
        if len(zeros):
            spec.add(zeros.real, zeros.imag, f"zeros {_name(sys, i)}",
                     style="scatter")
    spec.extra["discrete"] = bool(getattr(systems[0], "dt", 0))
    if plot:
        emit(spec)
    return spec


def rlocus(sys, kvect=None, plot: bool = True):
    """Root locus as gain varies."""
    data = _stab.root_locus(sys, K_max=(max(kvect) if kvect is not None
                                        else None))
    spec = FigureSpec("rlocus", "Root Locus", "Re", "Im")
    for branch in range(data.roots.shape[1]):
        column = data.roots[:, branch]
        spec.add(column.real, column.imag, f"branch {branch + 1}")
    spec.extra["K_marginal"] = data.K_marginal
    spec.extra["omega_marginal"] = data.omega_marginal
    if plot:
        emit(spec)
    return _PlotPair((data.roots, data.K_values), "root locus")


def figure_spec_for(sys, kind: str = "time"):
    """Build a figure without emitting it — for tests and custom renderers."""
    return {"time": step, "bode": bode, "nyquist": nyquist,
            "pzmap": pzmap}[kind](sys, plot=False)


# ──────────────────────────────────────────────────────────────
#  Modern control
# ──────────────────────────────────────────────────────────────

def ctrb(A, B=None):
    if B is None:
        A, B = np.asarray(A.A), np.asarray(A.B)
    return _struct.controllability_matrix(A, B)


def obsv(A, C=None):
    if C is None:
        A, C = np.asarray(A.A), np.asarray(A.C)
    return _struct.observability_matrix(A, C)


def gram(sys, which: str = "c"):
    """Gramian — via scipy's Lyapunov solver, so no slycot is needed."""
    return _struct.gramian(sys, which)


def hsvd(sys):
    """Hankel singular values."""
    return _struct.hankel_singular_values(sys)


def balred(sys, order: int):
    """Balanced truncation to ``order`` states."""
    return _struct.balanced_reduction(sys, order)[0]


def place(sys_or_A, B=None, poles=None):
    """Pole placement, returning ``K``. Accepts a system or ``(A, B, poles)``."""
    if B is None:
        return _fbk.place(sys_or_A, poles).K
    return _fbk.place(_ss.state_space(sys_or_A, B, np.eye(
        np.atleast_2d(sys_or_A).shape[0])), poles).K


def acker(A, B, poles):
    return _fbk.acker(_ss.state_space(
        A, B, np.eye(np.atleast_2d(A).shape[0])), poles).K


def lqr(sys, Q=None, R=None):
    """``(K, P, eigenvalues)`` — MATLAB's ``[K, S, e]``."""
    design = _fbk.lqr(sys, Q, R)
    return design.K, design.riccati, design.eigenvalues


def lqi(sys, Q=None, R=None):
    design = _fbk.lqi(sys, Q, R)
    return design.K, design.riccati, design.eigenvalues


def lqe(sys, W=None, V=None):
    """Kalman filter gain: ``(L, P, eigenvalues)``."""
    design = _obs.kalman(sys, W, V)
    return design.L, design.riccati, design.eigenvalues


kalman = lqe


def estim(sys, poles):
    """Luenberger observer gain ``L``."""
    return _obs.observer(sys, poles).L


def isctrb(sys) -> bool:
    return _struct.analyse_structure(sys).controllable


def isobsv(sys) -> bool:
    return _struct.analyse_structure(sys).observable


def canon(sys, form: str = "modal"):
    """Canonical form: ``modal``, ``companion``/``controllable``, ``observable``."""
    builder = {
        "modal": _ss.modal_form,
        "companion": _ss.controllable_form,
        "controllable": _ss.controllable_form,
        "reachable": _ss.controllable_form,
        "observable": _ss.observable_form,
    }
    if form not in builder:
        raise ValueError(
            f"unknown canonical form {form!r}; "
            f"use one of {', '.join(sorted(builder))}")
    return builder[form](sys)


# ──────────────────────────────────────────────────────────────
#  Discrete time
# ──────────────────────────────────────────────────────────────

def c2d(sys, dt: float, method: str = "zoh", prewarp=None):
    return _discrete.c2d(sys, dt, method, prewarp)


def d2c(sys, method: str = "zoh"):
    """
    Continuous equivalent. python-control has no ``d2c``; this one does.

    Returns the same kind of model it was given — a transfer function back for
    a transfer function — so ``d2c(c2d(G, Ts))`` round-trips to something you
    can compare with ``G`` directly.
    """
    recovered = _discrete.d2c(sys, method)
    if isinstance(sys, ctl.TransferFunction):
        return ctl.ss2tf(recovered)
    return recovered


def deadbeat(sys):
    return _discrete.deadbeat(sys)


# ──────────────────────────────────────────────────────────────
#  Controller design
# ──────────────────────────────────────────────────────────────

def pid(Kp=1.0, Ki=0.0, Kd=0.0, Tf=0.0):
    """PID transfer function."""
    from ..core.tuning import PIDParams, pid_tf
    return pid_tf(PIDParams(Kp=Kp, Ki=Ki, Kd=Kd, Tf=Tf))


def lead(K=1.0, alpha=0.1, tau=1.0):
    from ..core.tuning import LeadLagParams, lead_tf
    return lead_tf(LeadLagParams(K=K, alpha=alpha, tau=tau, is_lead=True))


def lag(K=1.0, alpha=10.0, tau=1.0):
    from ..core.tuning import LeadLagParams, lag_tf
    return lag_tf(LeadLagParams(K=K, alpha=alpha, tau=tau, is_lead=False))


def pade(T: float, order: int = 2):
    """Padé approximation of a delay."""
    return _tfu.pure_delay_pade(T, order)


def zn(sys, method: str = "ultimate", controller: str = "PID"):
    """Ziegler–Nichols tuning: ``'ultimate'`` or ``'step'``."""
    from ..core.tuning import zn_step, zn_ultimate
    result = (zn_ultimate(sys) if method == "ultimate" else zn_step(sys))
    return getattr(result, f"{controller}_params")


def errconst(sys) -> dict[str, float]:
    """Static error constants and steady-state errors."""
    report = _perf.analyse_performance(sys)
    return {"Type": report.system_type, "Kp": report.Kp, "Kv": report.Kv,
            "Ka": report.Ka, "ess_step": report.ess_step,
            "ess_ramp": report.ess_ramp, "ess_parabola": report.ess_parabola}


# ──────────────────────────────────────────────────────────────
#  Simulation
# ──────────────────────────────────────────────────────────────

def sim(model, t_end: float = 10.0, **kwargs):
    """Run a Simulink model. ``sim(model, 20)``."""
    from ..sim import simulate
    return simulate(model, t_end=t_end, **kwargs)


def linearize(model, input_port: str, output_port: str, **kwargs):
    """Linearise a Simulink model about an operating point."""
    from ..sim.linearize import linearize as _lin
    return _lin(model, input_port, output_port, **kwargs).transfer_function()


# ──────────────────────────────────────────────────────────────
#  Namespace assembly
# ──────────────────────────────────────────────────────────────

#: Grouped for the help listing, and so the workspace browser can tell a
#: command from a user variable.
_GROUPS: dict[str, tuple[str, ...]] = {
    "Build": ("tf", "ss", "zpk", "tf2ss", "ss2tf", "pade", "pid", "lead",
              "lag"),
    "Connect": ("series", "parallel", "feedback", "minreal"),
    "Inspect": ("pole", "zero", "damp", "dcgain", "stepinfo", "margin",
                "allmargin", "bandwidth", "routh", "jury", "errconst"),
    "Time": ("step", "impulse", "lsim", "initial", "ramp"),
    "Frequency": ("bode", "nyquist", "nichols", "pzmap", "rlocus"),
    "State space": ("ctrb", "obsv", "gram", "hsvd", "balred", "canon",
                    "isctrb", "isobsv"),
    "Design": ("place", "acker", "lqr", "lqi", "lqe", "kalman", "estim",
               "zn"),
    "Discrete": ("c2d", "d2c", "deadbeat"),
    "Simulink": ("sim", "linearize"),
}


def build_namespace(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    The dictionary a console session starts with.

    numpy is available as ``np`` and python-control as ``ctl``, so anything
    the aliases do not cover is still one import away rather than a dead end.
    """
    namespace: dict[str, Any] = {
        "__name__": "__console__",
        "np": np, "numpy": np, "ctl": ctl, "control": ctl,
        "pi": math.pi, "inf": math.inf, "j": 1j, "i": 1j,
        "linspace": np.linspace, "logspace": np.logspace,
        "arange": np.arange, "zeros": np.zeros, "ones": np.ones,
        "eye": np.eye, "diag": np.diag, "sqrt": np.sqrt, "exp": np.exp,
        "abs": np.abs, "real": np.real, "imag": np.imag,
        "roots": np.roots, "poly": np.poly, "conv": np.convolve,
        "help_fm": describe_api,
    }
    for names in _GROUPS.values():
        for name in names:
            namespace[name] = globals()[name]
    namespace["s"] = ctl.tf([1, 0], [1])
    if extra:
        namespace.update(extra)
    return namespace


def command_names() -> set[str]:
    """Every name the API installs — so the workspace can hide them."""
    return set(build_namespace())


def describe_api() -> str:
    """The help text ``help_fm()`` prints."""
    lines = ["FakeMatlab console — MATLAB-shaped commands over Python.", ""]
    for group, names in _GROUPS.items():
        lines.append(f"  {group:12s} {'  '.join(names)}")
    lines += [
        "",
        "  's' is the Laplace variable:  G = 1/(s**2 + 2*s + 1)",
        "  numpy is 'np', python-control is 'ctl' — anything not aliased is",
        "  still reachable rather than out of bounds.",
        "",
        "  This is Python, not MATLAB: commas between list elements, 0-based",
        "  indexing, ** for powers.",
    ]
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────────────────

def _name(sys, index: int) -> str:
    label = getattr(sys, "name", None)
    if isinstance(label, str) and label and not label.startswith("sys["):
        return label
    return f"sys{index + 1}"


def _fmt_complex(z: complex) -> str:
    if abs(z.imag) < 1e-12:
        return f"{z.real:.4g}"
    sign = "+" if z.imag >= 0 else "-"
    return f"{z.real:.4g} {sign} {abs(z.imag):.4g}i"

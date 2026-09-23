"""
The LTI Viewer's arithmetic: a collection of systems → plottable curves.
=======================================================================

MATLAB's LTI Viewer is one gesture repeated: pick a response type, see every
loaded system on the same axes, right-click to add a *characteristic* — peak
response, settling time, stability margins — and the marker appears on every
curve at once.

This module does that part and nothing else. It returns
:class:`ViewerData` — plain arrays and labelled marks — and never touches Qt,
so every characteristic can be checked against an analytic value in a test.

**Frequencies are always raw rad/s here, never log₁₀.** The renderer applies
the log transform (see :mod:`fakematlab.ui.plots`). Emitting log coordinates
from this module is exactly the mistake that truncated every Bode plot in v1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import control as ctl
import numpy as np

from .collection import Entry, SystemCollection
from .freqresp import bode, nichols, nyquist
from .timeresp import (_auto_tspan, compute_step_metrics, impulse_response,
                       ramp_response, step_response)


class ResponseKind(str, Enum):
    STEP = "Step"
    IMPULSE = "Impulse"
    RAMP = "Ramp"
    BODE = "Bode"
    NYQUIST = "Nyquist"
    NICHOLS = "Nichols"
    PZMAP = "Pole-zero map"


class Characteristic(str, Enum):
    PEAK = "Peak response"
    SETTLING = "Settling time (±2%)"
    RISE = "Rise time (10–90%)"
    STEADY_STATE = "Steady state"
    MARGINS = "Stability margins"
    PEAK_GAIN = "Peak gain"
    BANDWIDTH = "Bandwidth (−3 dB)"


#: Which characteristics mean anything for which response.
#:
#: Deliberately not "all of them everywhere": a rise time on a Nyquist plot
#: has nowhere to go, and a settling time on a ramp response is not defined.
#: MATLAB greys out the ones that do not apply; so does this.
CHARACTERISTICS: dict[ResponseKind, tuple[Characteristic, ...]] = {
    ResponseKind.STEP: (Characteristic.PEAK, Characteristic.SETTLING,
                        Characteristic.RISE, Characteristic.STEADY_STATE),
    ResponseKind.IMPULSE: (Characteristic.PEAK,),
    ResponseKind.RAMP: (),
    ResponseKind.BODE: (Characteristic.MARGINS, Characteristic.PEAK_GAIN,
                        Characteristic.BANDWIDTH),
    ResponseKind.NYQUIST: (Characteristic.MARGINS,),
    ResponseKind.NICHOLS: (Characteristic.MARGINS,),
    ResponseKind.PZMAP: (),
}

#: Response kinds drawn against a logarithmic frequency axis.
LOG_FREQUENCY_KINDS = (ResponseKind.BODE,)


@dataclass
class Curve:
    """One line on one panel."""

    name: str
    x: np.ndarray
    y: np.ndarray
    colour: int = 0
    style: str = "line"        # "line" | "dashed" | "poles" | "zeros"
    panel: str = "main"        # "main" | "phase"


@dataclass
class Mark:
    """One annotated point — what a *characteristic* produces."""

    name: str
    x: float
    y: float
    label: str
    colour: int = 0
    panel: str = "main"
    kind: str = "point"        # "point" | "vline" | "hline"


@dataclass
class ViewerData:
    kind: ResponseKind
    curves: list[Curve] = field(default_factory=list)
    marks: list[Mark] = field(default_factory=list)
    xlabel: str = ""
    ylabel: str = ""
    phase_label: str = ""
    log_x: bool = False
    aspect_locked: bool = False
    panels: tuple[str, ...] = ("main",)
    note: str = ""

    def curves_on(self, panel: str) -> list[Curve]:
        return [c for c in self.curves if c.panel == panel]

    def marks_on(self, panel: str) -> list[Mark]:
        return [m for m in self.marks if m.panel == panel]


# ──────────────────────────────────────────────────────────────
#  Entry point
# ──────────────────────────────────────────────────────────────

def compute(collection: SystemCollection, kind: ResponseKind,
            characteristics: set[Characteristic] | None = None,
            t_final: float | None = None) -> ViewerData:
    """
    Every visible system in ``collection``, as ``kind``, with the requested
    characteristics marked.

    A system that cannot produce the requested response — an unstable one
    asked for its bandwidth, say — contributes its curve and simply no mark.
    It does not remove the other systems' marks, and it does not raise.
    """
    wanted = {c for c in (characteristics or set())
              if c in CHARACTERISTICS[kind]}
    builder = {
        ResponseKind.STEP: _time,
        ResponseKind.IMPULSE: _time,
        ResponseKind.RAMP: _time,
        ResponseKind.BODE: _bode,
        ResponseKind.NYQUIST: _nyquist,
        ResponseKind.NICHOLS: _nichols,
        ResponseKind.PZMAP: _pzmap,
    }[kind]
    return builder(collection, kind, wanted, t_final)


# ──────────────────────────────────────────────────────────────
#  Time responses
# ──────────────────────────────────────────────────────────────

def _time(collection: SystemCollection, kind: ResponseKind,
          wanted: set[Characteristic], t_final: float | None) -> ViewerData:
    data = ViewerData(kind=kind, xlabel="Time (s)", ylabel="y(t)")

    # One time vector for every system. Letting each pick its own from
    # `_auto_tspan` would put a fast system's whole transient in the first
    # tenth of the axis while a slow one spans it — which is precisely the
    # comparison the viewer exists to make, drawn so it cannot be made.
    t = _common_tspan(collection, t_final)

    compute_response = {
        ResponseKind.STEP: step_response,
        ResponseKind.IMPULSE: impulse_response,
        ResponseKind.RAMP: ramp_response,
    }[kind]

    for entry in collection.visible:
        resp = compute_response(entry.tf, t=t, label=entry.name)
        y = np.atleast_2d(resp.y)[0]
        data.curves.append(Curve(entry.name, resp.t, y, entry.colour))

        if kind is ResponseKind.RAMP:
            # The reference itself, so the steady-state lag is visible.
            continue
        if kind is ResponseKind.IMPULSE:
            if Characteristic.PEAK in wanted:
                idx = int(np.argmax(np.abs(y)))
                data.marks.append(Mark(
                    entry.name, float(resp.t[idx]), float(y[idx]),
                    f"peak {y[idx]:.4g} at t={resp.t[idx]:.3g} s",
                    entry.colour))
            continue
        _step_marks(data, entry, resp, wanted)

    if kind is ResponseKind.RAMP and data.curves:
        t_ref = data.curves[0].x
        data.curves.append(Curve("reference r(t) = t", t_ref, t_ref,
                                 colour=-1, style="dashed"))
    return data


def _common_tspan(collection: SystemCollection,
                  t_final: float | None) -> np.ndarray | None:
    """
    A time vector wide enough for the slowest visible system.

    Returns ``None`` for an empty collection so the per-system default still
    applies, and never grows the window by more than 50× the fastest system's
    own — one marginally stable member should not flatten everything else.
    """
    if t_final and t_final > 0:
        return np.linspace(0.0, float(t_final), 2000)
    spans = [float(_auto_tspan(entry.tf)[-1]) for entry in collection.visible]
    if not spans:
        return None
    end = min(max(spans), 50.0 * min(spans))
    return np.linspace(0.0, end, 2000)


def _step_marks(data: ViewerData, entry: Entry, resp,
                wanted: set[Characteristic]) -> None:
    """The four step characteristics, from the shared metrics routine."""
    if not wanted:
        return
    metrics = compute_step_metrics(resp)
    y = np.atleast_2d(resp.y)[0]

    if Characteristic.PEAK in wanted and np.isfinite(metrics.tp):
        data.marks.append(Mark(
            entry.name, metrics.tp, metrics.y_max,
            f"peak {metrics.y_max:.4g} at t={metrics.tp:.3g} s"
            + (f"  ({metrics.Mp_pct:.1f}% overshoot)"
               if np.isfinite(metrics.Mp_pct) else ""),
            entry.colour))

    if Characteristic.SETTLING in wanted and np.isfinite(metrics.ts_2pct):
        idx = int(np.argmin(np.abs(resp.t - metrics.ts_2pct)))
        data.marks.append(Mark(
            entry.name, metrics.ts_2pct, float(y[idx]),
            f"ts(±2%) = {metrics.ts_2pct:.3g} s", entry.colour))

    if Characteristic.RISE in wanted and np.isfinite(metrics.tr_1090):
        idx = int(np.argmin(np.abs(resp.t - metrics.tr_1090)))
        data.marks.append(Mark(
            entry.name, metrics.tr_1090, float(y[idx]),
            f"tr(10–90%) = {metrics.tr_1090:.3g} s", entry.colour))

    if Characteristic.STEADY_STATE in wanted and np.isfinite(metrics.y_inf):
        data.marks.append(Mark(
            entry.name, float(resp.t[-1]), metrics.y_inf,
            f"y∞ = {metrics.y_inf:.4g}", entry.colour, kind="hline"))


# ──────────────────────────────────────────────────────────────
#  Frequency responses
# ──────────────────────────────────────────────────────────────

def _bode(collection: SystemCollection, kind: ResponseKind,
          wanted: set[Characteristic], _t) -> ViewerData:
    data = ViewerData(
        kind=kind, xlabel="ω (rad/s)", ylabel="|G| (dB)",
        phase_label="Phase (°)", log_x=True, panels=("main", "phase"),
        note="Margins treat each plotted system as an open loop L(s).",
    )
    for entry in collection.visible:
        bd = bode(entry.tf)
        data.curves.append(Curve(entry.name, bd.omega, bd.mag_dB,
                                 entry.colour))
        data.curves.append(Curve(entry.name, bd.omega, bd.phase_deg,
                                 entry.colour, panel="phase"))

        if Characteristic.MARGINS in wanted:
            if np.isfinite(bd.wc) and bd.wc > 0:
                data.marks.append(Mark(
                    entry.name, bd.wc, 0.0,
                    f"ωc = {bd.wc:.4g} rad/s", entry.colour))
                data.marks.append(Mark(
                    entry.name, bd.wc, -180.0 + bd.pm_deg,
                    f"PM = {bd.pm_deg:.1f}°", entry.colour, panel="phase"))
            if np.isfinite(bd.w180) and bd.w180 > 0 and np.isfinite(bd.gm_dB):
                data.marks.append(Mark(
                    entry.name, bd.w180, -bd.gm_dB,
                    f"GM = {bd.gm_dB:.2f} dB", entry.colour))

        if Characteristic.PEAK_GAIN in wanted:
            idx = int(np.argmax(bd.mag_dB))
            data.marks.append(Mark(
                entry.name, float(bd.omega[idx]), float(bd.mag_dB[idx]),
                f"peak |G| = {bd.mag_dB[idx]:.2f} dB "
                f"at ω={bd.omega[idx]:.4g}", entry.colour))

        if Characteristic.BANDWIDTH in wanted:
            w_bw = _bandwidth(bd.omega, bd.mag_dB)
            if np.isfinite(w_bw):
                data.marks.append(Mark(
                    entry.name, w_bw, bd.mag_dB[0] - 3.0,
                    f"ω(−3 dB) = {w_bw:.4g} rad/s", entry.colour))
    return data


def _bandwidth(omega: np.ndarray, mag_dB: np.ndarray) -> float:
    """
    First frequency at which the gain has dropped 3 dB below its low-frequency
    value. ``nan`` when the gain never does — an integrator, for instance,
    starts unbounded and only ever falls.
    """
    if len(omega) < 2:
        return float("nan")
    target = mag_dB[0] - 3.0
    below = np.nonzero(mag_dB <= target)[0]
    if not len(below) or below[0] == 0:
        return float("nan")
    i = int(below[0])
    # Interpolate in log ω, which is where the curve is nearly straight.
    x0, x1 = np.log10(omega[i - 1]), np.log10(omega[i])
    y0, y1 = mag_dB[i - 1], mag_dB[i]
    if abs(y1 - y0) < 1e-12:
        return float(omega[i])
    return float(10 ** (x0 + (target - y0) * (x1 - x0) / (y1 - y0)))


def _nyquist(collection: SystemCollection, kind: ResponseKind,
             wanted: set[Characteristic], _t) -> ViewerData:
    data = ViewerData(kind=kind, xlabel="Re L(jω)", ylabel="Im L(jω)",
                      aspect_locked=True)
    for entry in collection.visible:
        nd = nyquist(entry.tf)
        data.curves.append(Curve(entry.name, nd.H_pos.real, nd.H_pos.imag,
                                 entry.colour))
        data.curves.append(Curve(f"{entry.name} (ω<0)", nd.H_neg.real,
                                 nd.H_neg.imag, entry.colour, style="dashed"))
        if Characteristic.MARGINS in wanted and np.isfinite(nd.modulus_margin):
            idx = int(np.argmin(np.abs(nd.omega - nd.w_modulus)))
            point = nd.H_pos[idx]
            data.marks.append(Mark(
                entry.name, float(point.real), float(point.imag),
                f"modulus margin = {nd.modulus_margin:.3g} "
                f"at ω={nd.w_modulus:.4g}", entry.colour))
    return data


def _nichols(collection: SystemCollection, kind: ResponseKind,
             wanted: set[Characteristic], _t) -> ViewerData:
    data = ViewerData(kind=kind, xlabel="Phase (°)", ylabel="|L| (dB)")
    for entry in collection.visible:
        nd = nichols(entry.tf)
        data.curves.append(Curve(entry.name, nd.phase_deg, nd.mag_dB,
                                 entry.colour))
        if Characteristic.MARGINS in wanted:
            bd = bode(entry.tf)
            if np.isfinite(bd.wc) and bd.wc > 0:
                data.marks.append(Mark(
                    entry.name, -180.0 + bd.pm_deg, 0.0,
                    f"PM = {bd.pm_deg:.1f}°", entry.colour))
            if np.isfinite(bd.gm_dB):
                data.marks.append(Mark(
                    entry.name, -180.0, -bd.gm_dB,
                    f"GM = {bd.gm_dB:.2f} dB", entry.colour))
    return data


def _pzmap(collection: SystemCollection, kind: ResponseKind,
           wanted: set[Characteristic], _t) -> ViewerData:
    data = ViewerData(kind=kind, xlabel="Re", ylabel="Im")
    for entry in collection.visible:
        tf = entry.tf
        poles = np.atleast_1d(ctl.poles(tf))
        zeros = np.atleast_1d(ctl.zeros(tf))
        data.curves.append(Curve(f"{entry.name} poles", poles.real,
                                 poles.imag, entry.colour, style="poles"))
        if len(zeros):
            data.curves.append(Curve(f"{entry.name} zeros", zeros.real,
                                     zeros.imag, entry.colour, style="zeros"))
    return data

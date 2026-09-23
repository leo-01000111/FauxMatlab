"""
Plain-text analysis report — the "copy the numbers into my lab write-up" path.
=============================================================================
Collects everything the six tabs display into one MATLAB-flavoured text block:
the blocks, the derived transfer functions, poles and zeros, step metrics,
stability margins, the Nyquist count, steady-state errors and the internal
stability verdict.

Deliberately plain text: it pastes into a report, a commit message or an
email without carrying formatting along with it.
"""

from __future__ import annotations

import datetime as _dt

import control as ctl
import numpy as np

from .architecture import BLOCK_IDS, INPUT_SIGNALS, OUTPUT_SIGNALS, CourseArchitecture
from .freqresp import bode, nyquist
from .performance import analyse_performance, waterbed
from .tf_utils import analyse, factored_str
from .timeresp import compute_step_metrics, step_response

_WIDTH = 74


def _rule(char: str = "─") -> str:
    return char * _WIDTH


def _head(title: str) -> str:
    return f"\n{_rule()}\n{title}\n{_rule()}"


def _fmt(v, unit: str = "", fmt: str = ".5g") -> str:
    if v is None:
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if np.isnan(f):
        return "N/A"
    if np.isinf(f):
        return ("+∞" if f > 0 else "−∞") + unit
    return f"{f:{fmt}}{unit}"


def _tf_line(tf: ctl.TransferFunction) -> str:
    return factored_str(tf)


def text_report(arch: CourseArchitecture,
                title: str = "FakeMatlab analysis report") -> str:
    """Build the full report for an architecture."""
    out: list[str] = []
    stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    out.append(_rule("═"))
    out.append(f"{title}")
    out.append(f"generated {stamp}")
    out.append(_rule("═"))

    # ── Blocks ──
    out.append(_head("BLOCKS"))
    for bid in BLOCK_IDS:
        block = arch.get_block(bid)
        out.append(f"  {block.label:8s} = {_tf_line(block.tf)}"
                   f"      ({block.description})")

    # ── Derived transfer functions ──
    out.append(_head("DERIVED TRANSFER FUNCTIONS"))
    L = arch.loop_tf()
    out.append(f"  L = K₂·G·H      = {_tf_line(L)}")
    out.append(f"  S = 1/(1+L)     = {_tf_line(arch.sensitivity())}")
    out.append(f"  T = L/(1+L)     = {_tf_line(arch.compl_sensitivity())}")

    out.append("")
    out.append("  Closed-loop transfer functions (input → output):")
    for i in INPUT_SIGNALS:
        for o in OUTPUT_SIGNALS:
            out.append(f"    {i:>2s} → {o:<2s} : "
                       f"{_tf_line(arch.get_closed_loop_tf(i, o))}")

    # ── Poles and zeros of r → y ──
    ry = arch.get_closed_loop_tf("r", "y")
    info = analyse(ry)
    out.append(_head("CLOSED LOOP  r → y"))
    out.append(f"  order = {info.order}   type = {info.system_type}   "
               f"DC gain = {_fmt(info.dc_gain)}")
    out.append(f"  minimum phase: {'yes' if info.minimum_phase else 'NO'}")
    out.append("")
    out.append(f"  {'pole':>22s} {'ωn':>10s} {'ζ':>9s} {'τ':>10s}  kind")
    for p in info.poles:
        out.append(f"  {_cplx(p.value):>22s} {_fmt(p.wn):>10s} "
                   f"{_fmt(p.zeta):>9s} {_fmt(p.tau):>10s}  {p.kind}")
    if info.zeros:
        out.append("")
        for z in info.zeros:
            out.append(f"  zero: {_cplx(complex(z))}")

    # ── Internal stability ──
    out.append(_head("INTERNAL STABILITY  (ch.6, 1/26)"))
    for line in arch.internal_stability().summary().splitlines():
        out.append(f"  {line}")
    chi = arch.characteristic_polynomial()
    out.append("")
    out.append("  characteristic polynomial coefficients:")
    out.append(f"    {np.array2string(chi, precision=6, max_line_width=_WIDTH - 6)}")

    # ── Step metrics ──
    out.append(_head("STEP RESPONSE  r → y  (ch.3, 19–21/34)"))
    metrics = compute_step_metrics(step_response(ry))
    for key, value in metrics.as_dict().items():
        out.append(f"  {key:<26s} {_fmt(value):>14s}")

    # ── Frequency ──
    out.append(_head("STABILITY MARGINS  (ch.6, 15–24/26)"))
    bd = bode(L, closed_loop_tf=arch.compl_sensitivity(),
              sensitivity_tf=arch.sensitivity())
    nd = nyquist(L)
    rows = [
        ("Gain margin GM", _fmt(bd.gm_dB, " dB", ".3f")),
        ("Phase margin PM", _fmt(bd.pm_deg, "°", ".3f")),
        ("Gain crossover ωc", _fmt(bd.wc, " rad/s")),
        ("Phase crossover ω₁₈₀", _fmt(bd.w180, " rad/s")),
        ("Delay margin", _fmt(bd.dm_s, " s")),
        ("Modulus margin", _fmt(nd.modulus_margin)),
        ("Bandwidth (−3 dB of T)", _fmt(bd.bw_3dB, " rad/s")),
        ("Resonant peak Mr", _fmt(bd.Mr)),
        ("Peak sensitivity Ms", _fmt(bd.Ms)),
    ]
    for label, value in rows:
        out.append(f"  {label:<26s} {value:>14s}")
    out.append("")
    out.append(f"  Nyquist: N = {nd.encirclements}, P = {nd.P}, "
               f"Z = N + P = {nd.Z}  "
               f"→ {'stable' if nd.Z == 0 else f'{nd.Z} unstable CL pole(s)'}")

    # ── Performance ──
    out.append(_head("STEADY-STATE PERFORMANCE  (ch.7)"))
    rpt = analyse_performance(L, closed_loop_tf=arch.compl_sensitivity(),
                              bw_3dB=bd.bw_3dB)
    for line in rpt.summary.splitlines():
        out.append(f"  {line}")

    out.append("")
    wb = waterbed(L, sensitivity_tf=arch.sensitivity())
    out.append("  Bode–Freudenberg (ch.7, 18/20):")
    for line in wb.summary().splitlines():
        out.append(f"    {line}")

    out.append("")
    out.append(_rule("═"))
    return "\n".join(out)


def _cplx(z: complex) -> str:
    if abs(z.imag) < 1e-10:
        return f"{z.real:.6g}"
    sign = "+" if z.imag >= 0 else "−"
    return f"{z.real:.5g} {sign} {abs(z.imag):.5g}j"

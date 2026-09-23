"""
Frequency-domain analysis: Bode, Nyquist, Nichols, stability margins.
======================================================================
Provides rich annotated data for every plot (gain/phase crossover
frequencies, gain margin, phase margin, delay margin, −3 dB bandwidth,
resonant peak Mr, M-circles for Nyquist and Nichols, modulus margin) —
ch.4 34–46/46 and ch.6 15–26/26.

All frequency vectors are **raw ω in rad/s**. The plotting layer owns the
log-axis conversion; see :mod:`fakematlab.ui.plots`.
"""

from __future__ import annotations

from dataclasses import dataclass

import control as ctl
import numpy as np

# ──────────────────────────────────────────────────────────────
#  Result dataclasses
# ──────────────────────────────────────────────────────────────

@dataclass
class BodeData:
    """Bode plot data with annotated margins and frequency characteristics."""
    omega:   np.ndarray     # rad/s
    mag_dB:  np.ndarray     # 20·log10|G(jω)|
    phase_deg: np.ndarray   # arg G(jω) in degrees, unwrapped
    # Margins
    gm_dB:   float    # gain margin in dB  (inf → no phase crossover)
    pm_deg:  float    # phase margin in degrees
    dm_s:    float    # delay margin in seconds (= PM in rad / ω_c)
    wc:      float    # gain crossover frequency (0-dB crossing), rad/s
    w180:    float    # phase crossover frequency (−180° crossing), rad/s
    # Bandwidth / closed-loop peak
    bw_3dB:  float    # −3 dB bandwidth of closed-loop T, rad/s
    bw_0dB:  float    # = wc (gain crossover), kept for clarity
    Mr:      float    # resonant peak of |T(jω)|, magnitude (not dB)
    wr:      float    # frequency at which Mr occurs, rad/s
    Ms:      float    # peak of |S(jω)| — modulus margin is 1/Ms
    ws:      float    # frequency at which Ms occurs, rad/s
    # Stability
    stable:  bool     # of the *closed loop*, from its poles where known
    stability_known: bool = True
    note:    str = ""


@dataclass
class NyquistData:
    """Nyquist plot data (L(jω) for ω ∈ (−∞, +∞))."""
    omega:       np.ndarray   # positive ω half (0+, …)
    H_pos:       np.ndarray   # L(jω)   complex
    H_neg:       np.ndarray   # L(−jω)  complex  (conjugate of H_pos)
    encirclements: int        # N = number of CW encirclements of −1
    P:           int          # open-loop RHP poles
    Z:           int          # closed-loop RHP poles  Z = N + P
    modulus_margin: float     # shortest distance |L(jω) − (−1)|
    w_modulus:   float        # frequency where that shortest distance occurs
    gm_dB:       float
    pm_deg:      float
    wc:          float
    w180:        float
    # M-circle contours (iso-|T| loci) in the L-plane
    m_circles: list[tuple[float, np.ndarray]]  # list of (M_value, complex_path)


@dataclass
class NicholsData:
    """Nichols chart data: open-loop phase (x) against magnitude in dB (y)."""
    omega:     np.ndarray
    mag_dB:    np.ndarray
    phase_deg: np.ndarray
    #: (M_value, Nx2 array of [phase_deg, mag_dB]) — true Nichols M-contours.
    m_circles: list[tuple[float, np.ndarray]]


# ──────────────────────────────────────────────────────────────
#  Raw frequency response
# ──────────────────────────────────────────────────────────────

def response(tf: ctl.TransferFunction,
             omega: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    ``(magnitude, phase_rad)`` of ``tf`` at each ω.

    Uses ``control.frequency_response``; the older ``control.bode(plot=False)``
    tuple return is deprecated in python-control 0.10 and emits a
    ``FutureWarning`` on every call.
    """
    fr = ctl.frequency_response(tf, omega)
    mag = np.atleast_1d(np.squeeze(fr.magnitude)).astype(float)
    phase = np.atleast_1d(np.squeeze(fr.phase)).astype(float)
    return mag, phase


# ──────────────────────────────────────────────────────────────
#  Bode
# ──────────────────────────────────────────────────────────────

def bode(
    tf: ctl.TransferFunction,
    omega: np.ndarray | None = None,
    closed_loop_tf: ctl.TransferFunction | None = None,
    sensitivity_tf: ctl.TransferFunction | None = None,
) -> BodeData:
    """
    Bode data for ``tf`` — normally the open-loop ``L(s)``.

    ``closed_loop_tf`` supplies Mr and the −3 dB bandwidth, ``sensitivity_tf``
    supplies Ms. Both are derived as ``feedback(tf, 1)`` / ``1 − T`` when not
    given, which is only right for unity feedback — so callers that have the
    exact ones (the architecture does) should pass them.
    """
    if omega is None:
        omega = _auto_omega(tf)

    mag, phase = response(tf, omega)
    mag_dB = 20.0 * np.log10(np.maximum(mag, 1e-300))
    phase_deg = np.degrees(np.unwrap(phase))

    pm_deg, gm_dB, wpc, wgc = _margins(tf, mag, phase_deg, omega)

    # Delay margin: how much pure delay the loop tolerates before PM hits zero.
    if np.isfinite(wgc) and wgc > 0 and np.isfinite(pm_deg):
        dm_s = float(np.radians(abs(pm_deg)) / wgc)
    else:
        dm_s = float("inf")

    if closed_loop_tf is None:
        closed_loop_tf = _safe_unity_feedback(tf)

    bw_3dB, Mr, wr = _closed_loop_shape(closed_loop_tf, omega)

    if sensitivity_tf is None and closed_loop_tf is not None:
        sensitivity_tf = _safe_sensitivity(tf)
    Ms, ws = _peak(sensitivity_tf, omega)

    stable, known, note = _closed_loop_stability(tf, closed_loop_tf,
                                                 gm_dB, pm_deg)

    return BodeData(
        omega=omega, mag_dB=mag_dB, phase_deg=phase_deg,
        gm_dB=gm_dB, pm_deg=pm_deg, dm_s=dm_s,
        wc=float(wgc), w180=float(wpc),
        bw_3dB=bw_3dB, bw_0dB=float(wgc),
        Mr=Mr, wr=wr, Ms=Ms, ws=ws,
        stable=stable, stability_known=known, note=note,
    )


def stability_margins(tf) -> tuple[float, float, float, float, float, float]:
    """
    ``(pm_deg, gm_dB, w180, wc, sm, w_sm)`` from ``control.stability_margins``.

    That function returns **six** values in the order
    ``(gm, pm, sm, wpc, wgc, wms)`` — note ``sm``, the shortest distance to −1,
    sits third, between the margins and the crossover frequencies. Slicing the
    first four therefore yields ``wpc`` where ``wgc`` belongs and silently
    reports a stability margin as a frequency. This wrapper exists so that
    unpacking happens in exactly one place.
    """
    gm, pm, sm, wpc, wgc, wms = ctl.stability_margins(tf)
    gm_dB = float("inf") if (gm is None or not np.isfinite(gm) or gm <= 0) \
        else float(20.0 * np.log10(gm))
    pm_deg = float("inf") if pm is None or not np.isfinite(pm) else float(pm)
    return (pm_deg, gm_dB, _f(wpc), _f(wgc), _f(sm), _f(wms))


def _f(v) -> float:
    """Coerce to float, mapping ``None`` and non-finite values to NaN."""
    if v is None:
        return float("nan")
    v = float(v)
    return v if np.isfinite(v) else float("nan")


def _margins(tf, mag, phase_deg, omega):
    """
    ``(pm_deg, gm_dB, w_phase_cross, w_gain_cross)``.

    Delegates to :func:`stability_margins`, which searches the exact rational
    function rather than a sampled grid, so a crossover falling between two
    samples is still found. Falls back to interpolating the sampled curves if
    that raises.
    """
    try:
        pm_deg, gm_dB, wpc, wgc, _sm, _wms = stability_margins(tf)
        return pm_deg, gm_dB, wpc, wgc
    except Exception:
        return _margins_from_samples(mag, phase_deg, omega)


def _margins_from_samples(mag: np.ndarray, phase_deg: np.ndarray,
                          omega: np.ndarray):
    """Interpolated crossovers from the sampled curves (fallback path)."""
    gc_idxs = np.where(np.diff(np.sign(mag - 1.0)))[0]
    if len(gc_idxs):
        wgc = _interp_zero_cross(omega, mag - 1.0, gc_idxs[0])
        pm_deg = float(180.0 + np.interp(wgc, omega, phase_deg))
    else:
        wgc, pm_deg = float("nan"), float("inf")

    ph_shifted = phase_deg + 180.0
    pc_idxs = np.where(np.diff(np.sign(ph_shifted)))[0]
    if len(pc_idxs):
        wpc = _interp_zero_cross(omega, ph_shifted, pc_idxs[0])
        mag_at_pc = float(np.interp(wpc, omega, mag))
        gm_dB = -20.0 * np.log10(mag_at_pc) if mag_at_pc > 1e-300 else float("inf")
    else:
        wpc, gm_dB = float("nan"), float("inf")

    return pm_deg, gm_dB, wpc, wgc


def _interp_zero_cross(x: np.ndarray, y: np.ndarray, idx: int) -> float:
    """Linear interpolation to find the zero crossing between idx and idx+1."""
    x1, x2 = x[idx], x[idx + 1]
    y1, y2 = y[idx], y[idx + 1]
    if abs(y2 - y1) < 1e-300:
        return float(x1)
    return float(x1 + (x2 - x1) * (-y1) / (y2 - y1))


def _closed_loop_shape(cl_tf, omega) -> tuple[float, float, float]:
    """``(bw_3dB, Mr, wr)`` of the closed loop, all NaN if unavailable."""
    if cl_tf is None:
        return float("nan"), float("nan"), float("nan")
    try:
        mag, _ = response(cl_tf, omega)
    except Exception:
        return float("nan"), float("nan"), float("nan")

    peak_idx = int(np.argmax(mag))
    Mr, wr = float(mag[peak_idx]), float(omega[peak_idx])

    # −3 dB bandwidth is measured relative to the DC gain, not to 1: a loop
    # with |T(0)| = 0.5 has its −3 dB point at 0.354, not at 0.707.
    dc = float(mag[0])
    bw = float("nan")
    if dc > 1e-12:
        threshold = dc / np.sqrt(2.0)
        below = np.where(mag < threshold)[0]
        if len(below) and below[0] > 0:
            i = below[0] - 1
            bw = _interp_zero_cross(omega, mag - threshold, i)
    return bw, Mr, wr


def _peak(tf, omega) -> tuple[float, float]:
    """``(peak_magnitude, frequency)`` of a transfer function."""
    if tf is None:
        return float("nan"), float("nan")
    try:
        mag, _ = response(tf, omega)
    except Exception:
        return float("nan"), float("nan")
    i = int(np.argmax(mag))
    return float(mag[i]), float(omega[i])


def _closed_loop_stability(L, cl_tf, gm_dB, pm_deg) -> tuple[bool, bool, str]:
    """
    Closed-loop stability verdict.

    Positive margins do **not** imply stability when the open loop already has
    RHP poles — v1 reported ``stable=True`` for ``L = 1/(s−1)`` on exactly that
    reasoning. Decide from the closed-loop poles whenever we have them, and say
    so when we cannot.
    """
    if cl_tf is not None:
        try:
            poles = np.atleast_1d(ctl.poles(cl_tf))
            if len(poles):
                return bool(all(p.real < 0 for p in poles)), True, ""
        except Exception:
            pass
    try:
        P = int(sum(1 for p in np.atleast_1d(ctl.poles(L)) if p.real > 0))
    except Exception:
        P = 0
    margins_ok = bool(gm_dB > 0 and pm_deg > 0)
    if P > 0:
        return False, False, (
            f"Open loop has {P} RHP pole(s): gain and phase margins alone do "
            f"not decide stability here — use the Nyquist criterion (Z = N + P)."
        )
    return margins_ok, True, ""


def _safe_unity_feedback(tf):
    try:
        return ctl.feedback(tf, ctl.TransferFunction([1], [1]))
    except Exception:
        return None


def _safe_sensitivity(tf):
    try:
        return ctl.feedback(ctl.TransferFunction([1], [1]), tf)
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────
#  Nyquist
# ──────────────────────────────────────────────────────────────

def nyquist(
    tf: ctl.TransferFunction,
    omega: np.ndarray | None = None,
    m_circle_values: list[float] | None = None,
) -> NyquistData:
    """
    Nyquist data for the loop TF ``L(s)``, with the encirclement count.

    The count uses the winding number of the full contour about −1, and the
    verdict ``Z = N + P`` is the criterion as stated in ch.6, slide 10/26.
    """
    if omega is None:
        omega = _auto_omega(tf, min_pts=2000)
    if m_circle_values is None:
        m_circle_values = [0.5, 0.707, 1.0, 1.3, 2.0, 3.0, 5.0]

    mag, phase = response(tf, omega)
    phase_deg = np.degrees(np.unwrap(phase))
    H_pos = mag * np.exp(1j * phase)
    H_neg = np.conj(H_pos)                 # L(−jω) = conj L(jω) for real coefficients

    pm_deg, gm_dB, wpc, wgc = _margins(tf, mag, phase_deg, omega)

    # Modulus (shortest-distance) margin — ch.6, slide 23/26. Prefer the exact
    # value from the rational function; fall back to the sampled minimum.
    modulus = np.abs(H_pos + 1.0)
    i_min = int(np.argmin(modulus))
    modulus_margin = float(modulus[i_min])
    w_modulus = float(omega[i_min])
    try:
        _pm, _gm, _wpc, _wgc, sm, wms = stability_margins(tf)
        if np.isfinite(sm):
            modulus_margin = float(sm)
            w_modulus = wms if np.isfinite(wms) else w_modulus
    except Exception:
        pass

    N = _winding_number(H_pos, H_neg, centre=complex(-1, 0))
    P = int(sum(1 for p in np.atleast_1d(ctl.poles(tf)) if p.real > 0))

    circles = [(m, _m_circle(m)) for m in m_circle_values]

    return NyquistData(
        omega=omega, H_pos=H_pos, H_neg=H_neg,
        encirclements=N, P=P, Z=N + P,
        modulus_margin=modulus_margin, w_modulus=w_modulus,
        gm_dB=gm_dB, pm_deg=pm_deg, wc=float(wgc), w180=float(wpc),
        m_circles=circles,
    )


def _winding_number(H_pos: np.ndarray, H_neg: np.ndarray,
                    centre: complex) -> int:
    """CW encirclements of ``centre`` by the full Nyquist contour."""
    path = np.concatenate([H_neg[::-1], H_pos])
    shifted = path - centre
    finite = shifted[np.isfinite(shifted)]
    if len(finite) < 2:
        return 0
    total = float(np.unwrap(np.angle(finite))[-1] - np.unwrap(np.angle(finite))[0])
    return -int(np.round(total / (2 * np.pi)))     # CCW positive → return CW


def _m_circle(M: float, n: int = 400) -> np.ndarray:
    """
    The locus ``|L/(1+L)| = M`` in the ``L``-plane.

    A circle centred at ``(−M²/(M²−1), 0)`` with radius ``M/|M²−1|``; for
    ``M = 1`` it degenerates to the vertical line ``Re L = −½``.
    """
    if abs(M - 1.0) < 1e-8:
        return -0.5 + 1j * np.linspace(-10, 10, n)
    theta = np.linspace(0, 2 * np.pi, n)
    centre = -M ** 2 / (M ** 2 - 1.0)
    radius = abs(M / (M ** 2 - 1.0))
    return centre + radius * np.exp(1j * theta)


# ──────────────────────────────────────────────────────────────
#  Nichols
# ──────────────────────────────────────────────────────────────

def nichols(
    tf: ctl.TransferFunction,
    omega: np.ndarray | None = None,
    m_circle_values: list[float] | None = None,
) -> NicholsData:
    """Nichols chart: open-loop phase (x) against open-loop magnitude in dB (y)."""
    if omega is None:
        omega = _auto_omega(tf, min_pts=1000)
    if m_circle_values is None:
        m_circle_values = [0.25, 0.5, 0.707, 1.0, 1.3, 2.0, 3.0, 6.0]

    mag, phase = response(tf, omega)
    mag_dB = 20.0 * np.log10(np.maximum(mag, 1e-300))
    phase_deg = np.degrees(np.unwrap(phase))

    circles = [(M, nichols_m_contour(M)) for M in m_circle_values]
    return NicholsData(omega=omega, mag_dB=mag_dB, phase_deg=phase_deg,
                       m_circles=circles)


def nichols_m_contour(M: float, n: int = 721) -> np.ndarray:
    """
    The true constant-|T| contour in Nichols coordinates.

    v1 took the Nyquist M-circle and read off its own phase and magnitude,
    which traces a different curve entirely. The contour is found properly
    here: at each open-loop phase θ, solve ``|L/(1+L)| = M`` for ``x = |L|``::

        x²(1 − M²) − 2M²·cos θ·x − M² = 0

    and keep the positive root. Returns an ``N×2`` array of
    ``[phase_deg, mag_dB]``, with NaN rows separating disjoint branches so a
    plot does not join them with a stray line.
    """
    theta_deg = np.linspace(-359.0, -1.0, n)
    theta = np.radians(theta_deg)
    cos_t = np.cos(theta)

    out: list[tuple[float, float]] = []
    a = 1.0 - M ** 2
    for td, ct in zip(theta_deg, cos_t):
        b = -2.0 * M ** 2 * ct
        c = -M ** 2
        if abs(a) < 1e-12:                      # M = 1 → linear in x
            if abs(b) < 1e-12:
                continue
            roots = [-c / b]
        else:
            disc = b * b - 4 * a * c
            if disc < 0:
                out.append((np.nan, np.nan))    # branch gap
                continue
            sq = np.sqrt(disc)
            roots = [(-b + sq) / (2 * a), (-b - sq) / (2 * a)]
        positive = [r for r in roots if r > 1e-12]
        if not positive:
            out.append((np.nan, np.nan))
            continue
        x = max(positive) if M > 1.0 else min(positive)
        out.append((td, 20.0 * np.log10(x)))

    return np.array(out, dtype=float) if out else np.empty((0, 2))


# ──────────────────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────────────────

def _auto_omega(tf: ctl.TransferFunction,
                min_pts: int = 500,
                decades_before: float = 2.0,
                decades_after:  float = 2.0) -> np.ndarray:
    """Frequency grid spanning the system's features with margin either side."""
    poles = np.atleast_1d(ctl.poles(tf))
    zeros = np.atleast_1d(ctl.zeros(tf))
    freqs = [abs(p) for p in poles if abs(p) > 1e-6] + \
            [abs(z) for z in zeros if abs(z) > 1e-6]
    if freqs:
        w_lo = min(freqs) / 10 ** decades_before
        w_hi = max(freqs) * 10 ** decades_after
    else:
        w_lo, w_hi = 1e-2, 1e3
    w_lo = max(w_lo, 1e-4)
    w_hi = min(max(w_hi, w_lo * 10), 1e6)
    return np.logspace(np.log10(w_lo), np.log10(w_hi), min_pts)

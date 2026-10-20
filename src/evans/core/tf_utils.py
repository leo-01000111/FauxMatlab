"""
Transfer-function utilities: parsing, formatting, factoring, pole tables.
=========================================================================
All functions accept/return python-control TransferFunction objects.
"""

from __future__ import annotations

from dataclasses import dataclass

import control as ctl
import numpy as np
import sympy as sp

# ──────────────────────────────────────────────────────────────
#  Pole / zero dataclasses
# ──────────────────────────────────────────────────────────────

@dataclass
class PoleInfo:
    """Rich information about a single pole."""
    value: complex          # exact pole location
    real: float
    imag: float
    wn: float               # natural frequency  |p|
    zeta: float             # damping ratio  −Re(p)/|p|; nan if wn=0
    tau: float              # time constant  −1/Re(p); inf if Re(p)=0
    stable: bool            # Re(p) < 0
    oscillatory: bool       # Im(p) ≠ 0
    kind: str               # "real-stable", "real-unstable", "complex-stable",
                            # "complex-unstable", "integrator", "oscillator"


@dataclass
class SystemInfo:
    """Aggregated information about a TF."""
    tf: ctl.TransferFunction
    poles: list[PoleInfo]
    zeros: list[complex]
    dc_gain: float | complex    # G(0); may be inf if integrators present
    system_type: int            # number of poles at origin (0,1,2,…)
    stable: bool
    minimum_phase: bool         # all zeros in OLHP
    factored_str: str           # human-readable factored form
    order: int


# ──────────────────────────────────────────────────────────────
#  Parsing
# ──────────────────────────────────────────────────────────────

def from_coefficients(num: list[float], den: list[float]) -> ctl.TransferFunction:
    """Build TF from polynomial coefficient lists (highest power first)."""
    return ctl.TransferFunction(num, den)


def from_expression(expr: str) -> ctl.TransferFunction:
    """
    Parse a string like '(s+1)/(s**2 + 2*s + 1)' into a TF.
    Uses sympy to expand, then extracts poly coefficients.
    Supports '^' as exponentiation.
    """
    expr = expr.replace('^', '**')
    s = sp.Symbol('s')
    try:
        sym_expr = sp.sympify(expr, locals={'s': s})
    except Exception as exc:
        raise ValueError(f"Cannot parse expression '{expr}': {exc}") from exc

    # Bring to canonical N(s)/D(s)
    sym_expr = sp.cancel(sym_expr)
    n_sym, d_sym = sp.fraction(sym_expr)
    n_sym = sp.expand(n_sym)
    d_sym = sp.expand(d_sym)

    num = _sympy_poly_to_coeffs(n_sym, s)
    den = _sympy_poly_to_coeffs(d_sym, s)
    return ctl.TransferFunction(num, den)


def from_zpk(zeros: list[complex], poles: list[complex],
             gain: float) -> ctl.TransferFunction:
    """Build TF from zero-pole-gain description."""
    num = [gain] if not zeros else (gain * np.poly(zeros)).tolist()
    den = np.poly(poles).tolist() if poles else [1.0]
    # np.poly returns real array even for complex zeros/poles with conjugate pairs
    num = [float(c.real) if abs(c.imag) < 1e-10 else c for c in
           (np.array(num).flatten())]
    den = [float(c.real) if abs(c.imag) < 1e-10 else c for c in
           (np.array(den).flatten())]
    return ctl.TransferFunction(num, den)


def first_order(K: float = 1.0, tau: float = 1.0) -> ctl.TransferFunction:
    """K / (tau·s + 1)"""
    return ctl.TransferFunction([K], [tau, 1.0])


def second_order(K: float = 1.0, zeta: float = 0.5,
                 wn: float = 1.0) -> ctl.TransferFunction:
    """K·ωn² / (s² + 2·ζ·ωn·s + ωn²)"""
    return ctl.TransferFunction([K * wn**2], [1.0, 2 * zeta * wn, wn**2])


def integrator(K: float = 1.0) -> ctl.TransferFunction:
    """K/s"""
    return ctl.TransferFunction([K], [1.0, 0.0])


def pure_delay_pade(T: float, order: int = 2) -> ctl.TransferFunction:
    """
    Padé approximation of a pure delay ``e^{−Ts}``.

    ``control.pade`` returns a ``(num, den)`` tuple, so the result must be
    wrapped. (v1 returned the raw tuple — the wrapping code sat below an
    unconditional ``return`` and never ran.)

    The approximation is good to roughly ``ω·T < order``; above that the phase
    stops tracking the true delay, which is why the Frequency tab reports the
    delay margin from the exact ``PM/ω_c`` rather than from this model.
    """
    if T < 0:
        raise ValueError(f"delay must be non-negative, got {T}")
    if T == 0:
        return unity()
    if order < 1:
        raise ValueError(f"Padé order must be at least 1, got {order}")
    result = ctl.pade(T, order)
    if isinstance(result, ctl.TransferFunction):
        return result
    num, den = result
    return ctl.TransferFunction(num, den)


def unity() -> ctl.TransferFunction:
    """TF = 1."""
    return ctl.TransferFunction([1], [1])


# ──────────────────────────────────────────────────────────────
#  System analysis
# ──────────────────────────────────────────────────────────────

def dc_gain(tf: ctl.TransferFunction) -> float:
    """
    ``G(0)`` — the steady-state gain.

    Returns ``±inf`` for a system with integrators and ``nan`` for the
    indeterminate ``0/0`` (a zero at the origin cancelling a pole there).

    v1 guarded this with ``except ZeroDivisionError``, which never fires:
    numpy divides floats by zero to ``inf`` with a ``RuntimeWarning`` rather
    than raising, so every integrator produced a warning and an unguarded
    value.
    """
    num = float(np.polyval(np.atleast_1d(tf.num[0][0]), 0.0))
    den = float(np.polyval(np.atleast_1d(tf.den[0][0]), 0.0))
    if abs(den) < 1e-300:
        if abs(num) < 1e-300:
            return float("nan")          # 0/0 — indeterminate
        return float("inf") * np.sign(num)
    return num / den


def pole_info(p: complex) -> PoleInfo:
    """Compute rich info for a single pole."""
    r, im = float(p.real), float(p.imag)
    wn = float(abs(p))
    if wn < 1e-10:
        zeta = float('nan')
        kind = "integrator"
    else:
        zeta = -r / wn
        if abs(im) < 1e-8 * max(1.0, wn):
            kind = "real-stable" if r < 0 else "real-unstable"
        else:
            kind = "complex-stable" if r < 0 else "complex-unstable"
        if abs(r) < 1e-10 and abs(im) > 1e-10:
            kind = "oscillator"

    tau = (-1.0 / r) if abs(r) > 1e-10 else float('inf')
    return PoleInfo(
        value=p, real=r, imag=im, wn=wn, zeta=zeta, tau=tau,
        stable=r < 0,
        oscillatory=abs(im) > 1e-8 * max(1.0, wn),
        kind=kind,
    )


def analyse(tf: ctl.TransferFunction) -> SystemInfo:
    """Return a comprehensive SystemInfo for a TF."""
    poles = [pole_info(p) for p in ctl.poles(tf)]
    zeros_raw = list(ctl.zeros(tf))
    stable = all(p.stable for p in poles)

    dc = dc_gain(tf)

    # System type = multiplicity of root s=0 in denominator
    sys_type = _count_zero_poles(tf)

    # Minimum phase = all zeros in OLHP
    min_phase = all(z.real < 0 for z in zeros_raw) if zeros_raw else True

    factored = factored_str(tf)
    order = max(len(tf.den[0][0]) - 1, 0)

    return SystemInfo(
        tf=tf, poles=poles, zeros=zeros_raw,
        dc_gain=dc, system_type=sys_type, stable=stable,
        minimum_phase=min_phase, factored_str=factored, order=order,
    )


def _count_zero_poles(tf: ctl.TransferFunction) -> int:
    """Count poles at s=0 (system type)."""
    poles = ctl.poles(tf)
    return sum(1 for p in poles if abs(p) < 1e-6)


# ──────────────────────────────────────────────────────────────
#  Formatting
# ──────────────────────────────────────────────────────────────

def factored_str(tf: ctl.TransferFunction,
                 var: str = 's',
                 precision: int = 4) -> str:
    """
    Return a human-readable factored representation:
    K · (s - z1)(s - z2)… / [(s - p1)(s - p2)…]
    Complex conjugate pairs are written as quadratics.
    """
    num_roots = _clean_roots(ctl.zeros(tf))
    den_roots = _clean_roots(ctl.poles(tf))
    # Leading gain = ratio of leading coefficients
    num_coeffs = tf.num[0][0]
    den_coeffs = tf.den[0][0]
    if len(den_coeffs) == 0 or den_coeffs[0] == 0:
        return str(tf)
    gain = num_coeffs[0] / den_coeffs[0]

    def fmt_num(v: float, prec: int) -> str:
        """Format a number, dropping trailing zeros."""
        return f"{v:.{prec}g}"

    def roots_to_factors(roots: list[complex]) -> str:
        used = [False] * len(roots)
        parts: list[str] = []
        for i, r in enumerate(roots):
            if used[i]:
                continue
            # Find conjugate pair
            if abs(r.imag) > 1e-6:
                conj_idx = None
                for j in range(i + 1, len(roots)):
                    if not used[j] and abs(roots[j] - r.conjugate()) < 1e-6:
                        conj_idx = j
                        break
                if conj_idx is not None:
                    used[i] = used[conj_idx] = True
                    # (s - r)(s - r*) = s² - 2·Re(r)·s + |r|²
                    a = -2 * r.real
                    b = abs(r) ** 2
                    s_term = f"({var}²"
                    if abs(a) > 1e-8:
                        s_term += f" {'+' if a >= 0 else '-'} {fmt_num(abs(a), precision)}{var}"
                    if abs(b) > 1e-8:
                        s_term += f" {'+' if b >= 0 else '-'} {fmt_num(abs(b), precision)}"
                    parts.append(s_term + ")")
                    continue
            # Real root
            used[i] = True
            if abs(r.real) < 1e-8:
                parts.append(var)
            else:
                sign = '+' if -r.real >= 0 else '-'
                parts.append(f"({var} {sign} {fmt_num(abs(r.real), precision)})")
        return _collapse_powers(parts) if parts else "1"

    num_str = roots_to_factors(num_roots)
    den_str = roots_to_factors(den_roots)
    gain_str = fmt_num(gain, precision)

    gain_part = "" if abs(gain - 1.0) < 1e-8 else gain_str + " · "

    if num_str == "1" and not gain_part:
        top = "1"
    else:
        top = gain_part + num_str if num_str != "1" else gain_str

    # A constant is a constant — "1 / 1" and "2.5 / 1" read as mistakes.
    if den_str == "1":
        return top
    return f"{top} / {den_str}"


def _clean_roots(roots, tol: float = 1e-4) -> list[complex]:
    """
    Snap numerically-real roots onto the real axis, and round near-equal ones
    together, for display.

    ``np.roots`` splits a repeated real root into a near-conjugate cluster:
    the triple root of ``(s+1)³`` comes back as ``-1 ± 5.7e-6j`` plus
    ``-1.000007``. Without this, the factored form of ``1/(s+1)³`` prints as
    ``(s² + 2s + 1)(s + 1)`` — correct arithmetic, unreadable algebra. The
    error in an ``m``-fold root grows like ``eps^(1/m)``, so the tolerance has
    to be far looser than machine precision.

    Display only — analysis keeps the raw roots.
    """
    cleaned: list[complex] = []
    for r in np.atleast_1d(roots):
        r = complex(r)
        scale = max(1.0, abs(r))
        if abs(r.imag) < tol * scale:
            r = complex(r.real, 0.0)
        cleaned.append(r)

    # Merge clusters so repeated roots compare equal and collapse to a power.
    merged: list[complex] = []
    for r in cleaned:
        for seen in merged:
            if abs(r - seen) < tol * max(1.0, abs(seen)):
                r = seen
                break
        merged.append(r)
    return merged


def _collapse_powers(parts: list[str]) -> str:
    """
    ``(s+1)(s+1)(s)(s)`` → ``(s+1)² s²``.

    Repeated factors are common (a double integrator, a critically damped
    pair) and writing them out is noise, not information.
    """
    out: list[str] = []
    i = 0
    while i < len(parts):
        j = i
        while j < len(parts) and parts[j] == parts[i]:
            j += 1
        count = j - i
        out.append(parts[i] if count == 1 else parts[i] + _superscript(count))
        i = j
    # Space out bare variables so "s s" does not read as one symbol.
    return "".join(
        part if part.startswith("(") else f"{part} " for part in out
    ).strip()


def _superscript(n: int) -> str:
    digits = {"0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴",
              "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹"}
    return "".join(digits[ch] for ch in str(n))


def coefficients_str(tf: ctl.TransferFunction, var: str = 's') -> str:
    """Return TF as 'num_poly / den_poly' string."""
    def poly_str(coeffs: np.ndarray) -> str:
        terms = []
        n = len(coeffs) - 1
        for i, c in enumerate(coeffs):
            power = n - i
            if abs(c) < 1e-12:
                continue
            c_str = f"{c:.4g}" if abs(c - 1.0) > 1e-8 or power == 0 else ""
            if power == 0:
                terms.append(f"{c:.4g}")
            elif power == 1:
                terms.append(f"{c_str}{var}")
            else:
                terms.append(f"{c_str}{var}^{power}")
        return " + ".join(terms) if terms else "0"

    n = poly_str(tf.num[0][0])
    d = poly_str(tf.den[0][0])
    return f"({n}) / ({d})"


# ──────────────────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────────────────

def _sympy_poly_to_coeffs(poly_expr: sp.Expr, var: sp.Symbol) -> list[float]:
    """Convert a sympy polynomial expression to a coefficient list (high→low)."""
    poly = sp.Poly(sp.expand(poly_expr), var)
    return [float(c) for c in poly.all_coeffs()]


# ──────────────────────────────────────────────────────────────
#  Preset library (useful for demos and quick starts)
# ──────────────────────────────────────────────────────────────

PRESETS: dict[str, tuple[str, ctl.TransferFunction]] = {
    "first_order":        ("K/(τs+1)",     first_order(1.0, 1.0)),
    "second_order_under": ("ωn²/(s²+2ζωns+ωn²)",  second_order(1.0, 0.3, 1.0)),
    "second_order_crit":  ("ωn²/(s+ωn)²", second_order(1.0, 1.0, 1.0)),
    "second_order_over":  ("ωn²/(s²+2ζωns+ωn²)",  second_order(1.0, 2.0, 1.0)),
    "integrator":         ("K/s",          integrator(1.0)),
    "double_integrator":  ("K/s²",         ctl.TransferFunction([1], [1, 0, 0])),
    "non_min_phase":      ("(-s+1)/(s+1)", ctl.TransferFunction([-1, 1], [1, 1])),
    "unstable_first":     ("1/(s-1)",      ctl.TransferFunction([1], [1, -1])),
    "satellite":          ("1/s²",         ctl.TransferFunction([1], [1, 0, 0])),
}

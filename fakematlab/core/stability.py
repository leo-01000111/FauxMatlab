"""
Stability analysis: Routh table, Nyquist criterion, root locus.
================================================================
Routh is implemented symbolically (sympy) so the user can enter a
free parameter K and the table shows which column entries change sign.
"""

from __future__ import annotations

from dataclasses import dataclass

import control as ctl
import numpy as np
import sympy as sp

# ──────────────────────────────────────────────────────────────
#  Routh table
# ──────────────────────────────────────────────────────────────

@dataclass
class RouthResult:
    """Result of Routh-Hurwitz analysis."""
    table:          list[list]    # 2-D list (sympy exprs or floats)
    poly_coeffs:    list          # input characteristic polynomial coefficients
    n_sign_changes: int           # number of sign changes in first column
    n_rhp_poles:    int           # = n_sign_changes
    stable:         bool
    K_stable_range: str           # human-readable range of K for stability
    first_col:      list          # first column of table (sympy expressions)
    is_symbolic:    bool          # True if K is a free parameter
    symbol:         sp.Symbol | None


def routh_table(
    char_poly_coeffs: list,       # highest-power first, may contain sympy expr
    symbol: sp.Symbol | None = None,
) -> RouthResult:
    """
    Build the Routh array for characteristic polynomial a_n s^n + … + a_0.

    coeffs may be a mix of floats and sympy expressions containing `symbol`.
    If symbol is None, coefficients are treated as pure numbers.
    """
    # Convert to sympy if needed
    coeffs = [sp.sympify(c) for c in char_poly_coeffs]
    n = len(coeffs) - 1  # polynomial degree

    # Build Routh array (n+1 rows × ceil((n+1)/2) cols)
    cols = (n + 2) // 2
    arr = [[sp.Integer(0)] * cols for _ in range(n + 1)]

    # Fill first two rows
    for i, c in enumerate(coeffs[0::2]):   # even powers
        if i < cols:
            arr[0][i] = c
    for i, c in enumerate(coeffs[1::2]):   # odd powers
        if i < cols:
            arr[1][i] = c

    # Iteratively build remaining rows
    for row in range(2, n + 1):
        prev  = arr[row - 1]
        prev2 = arr[row - 2]
        # Leading term of previous row
        p0 = sp.simplify(prev[0]) if symbol else prev[0]
        if p0 == 0:
            # Replace zero row with epsilon-row (can signal special case)
            p0 = sp.Symbol('epsilon_small', positive=True)
        for col in range(cols - 1):
            if col + 1 < cols:
                num = prev2[col + 1] * p0 - prev2[0] * prev[col + 1]
                den = p0
                val = sp.simplify(num / den) if symbol else (num / den)
                arr[row][col] = val
            else:
                arr[row][col] = sp.Integer(0)

    # First column
    first_col = [arr[row][0] for row in range(n + 1)]
    first_col_simplified = [sp.simplify(c) if symbol else c
                            for c in first_col]

    # Count sign changes in first column (numeric only for pure numeric)
    if symbol is None:
        n_changes = _count_sign_changes_numeric(
            [float(c) for c in first_col_simplified]
        )
        stable = n_changes == 0
        K_range = "stable" if stable else f"{n_changes} RHP pole(s)"
    else:
        n_changes = -1   # cannot count symbolically in general
        stable = False   # unknown
        K_range = _symbolic_stability_range(first_col_simplified, symbol)

    return RouthResult(
        table=arr,
        poly_coeffs=char_poly_coeffs,
        n_sign_changes=max(n_changes, 0),
        n_rhp_poles=max(n_changes, 0),
        stable=stable,
        K_stable_range=K_range,
        first_col=first_col_simplified,
        is_symbolic=symbol is not None,
        symbol=symbol,
    )


def routh_from_closed_loop(
    G: ctl.TransferFunction,
    K2: ctl.TransferFunction | None = None,
    symbol: sp.Symbol | None = None,
    K_sym: sp.Symbol | None = None,
) -> RouthResult:
    """
    Build Routh table for the closed-loop characteristic polynomial 1 + K·K2·G.
    If K_sym is provided, it appears symbolically in the table.
    """
    if K2 is None:
        K2 = ctl.TransferFunction([1], [1])

    L = K2 * G
    # Characteristic polynomial = den(L) + num(L)  (for unity feedback)
    num = L.num[0][0]
    den = L.den[0][0]
    # char poly = den + num (since 1 + L = 0)
    # Handle length difference
    max_len = max(len(num), len(den))
    num_pad = np.pad(num, (max_len - len(num), 0))
    den_pad = np.pad(den, (max_len - len(den), 0))
    char_poly = (den_pad + num_pad).tolist()

    if K_sym is not None:
        # Re-derive symbolically with K as a free symbol
        # num_sym = K_sym * (num part from K2*G)
        # This requires symbolic poly manipulation
        K = K_sym
        num_K = [K * c for c in num]
        max_l = max(len(num_K), len(den))
        np_K  = [sp.Integer(0)] * (max_l - len(num_K)) + [sp.sympify(c) for c in num_K]
        dp    = [sp.Integer(0)] * (max_l - len(den))   + [sp.sympify(c) for c in den]
        char_poly_sym = [a + b for a, b in zip(dp, np_K)]
        return routh_table(char_poly_sym, symbol=K_sym)

    return routh_table(char_poly, symbol=symbol)


def _count_sign_changes_numeric(first_col: list[float]) -> int:
    """Count sign changes in a list of floats, ignoring zeros."""
    signs = [np.sign(v) for v in first_col if abs(v) > 1e-12]
    return sum(1 for i in range(len(signs) - 1) if signs[i] * signs[i + 1] < 0)


def _symbolic_stability_range(first_col: list, symbol: sp.Symbol) -> str:
    """
    The range of ``symbol`` for which the system is stable.

    Routh–Hurwitz (ch.6, slide 6/26): with a positive leading coefficient, the
    system is stable exactly when **every** first-column entry is positive.
    That is a conjunction of polynomial inequalities in one unknown, which
    sympy can reduce to an interval.

    v1 called ``solve(expr > 0)`` on each entry separately and joined the
    string forms, so it never intersected them and reported "Cannot determine
    symbolically" for even the standard textbook case.

    Returns something like ``0 < K < 6``, or a plain-language reason when no
    such range exists.
    """
    conditions = []
    for expr in first_col:
        expr = sp.simplify(expr)
        if expr.free_symbols & {symbol}:
            conditions.append(sp.Gt(expr, 0))
        elif expr.is_number and expr <= 0:
            # A constant entry that is already non-positive: no value of the
            # free parameter can rescue it.
            return (f"Unstable for every {symbol}: the first column contains "
                    f"the constant {expr}, which is not positive.")

    if not conditions:
        return (f"The first column does not depend on {symbol}; "
                f"stability is independent of it.")

    try:
        solution = sp.reduce_inequalities(conditions, symbol)
    except (NotImplementedError, sp.PolynomialError, TypeError) as exc:
        return (f"Could not reduce the stability conditions symbolically "
                f"({exc}). The K-dependent entries are shown in the table.")

    if solution is sp.false or solution == False:          # noqa: E712
        return f"No value of {symbol} makes the system stable."
    if solution is sp.true or solution == True:            # noqa: E712
        return f"Stable for every {symbol}."
    return _pretty_inequality(solution, symbol)


def _pretty_inequality(solution, symbol: sp.Symbol) -> str:
    """Render a sympy inequality set as ``0 < K < 6`` rather than ``(0 < K) & (K < 6)``."""
    rels = list(solution.args) if isinstance(solution, sp.And) else [solution]
    lower = upper = None
    others = []
    for rel in rels:
        if not isinstance(rel, (sp.StrictLessThan, sp.LessThan,
                                sp.StrictGreaterThan, sp.GreaterThan)):
            others.append(rel)
            continue
        # Normalise to have the symbol on the left.
        if rel.lhs == symbol:
            bound, is_upper = rel.rhs, isinstance(
                rel, (sp.StrictLessThan, sp.LessThan))
        elif rel.rhs == symbol:
            bound, is_upper = rel.lhs, isinstance(
                rel, (sp.StrictGreaterThan, sp.GreaterThan))
        else:
            others.append(rel)
            continue
        # Without assumptions on the symbol, sympy states unbounded sides
        # explicitly as ±oo. Those are not constraints, so drop them —
        # otherwise "K > 0" is reported as "0 < K < oo".
        if bound in (sp.oo, -sp.oo) or bound.has(sp.zoo):
            continue
        if is_upper:
            upper = bound if upper is None else sp.Min(upper, bound)
        else:
            lower = bound if lower is None else sp.Max(lower, bound)

    def num(v):
        f = float(v)
        if not np.isfinite(f):
            return "∞" if f > 0 else "−∞"
        return f"{f:g}" if abs(f - round(f)) > 1e-12 else f"{int(round(f))}"

    if lower is not None and upper is not None:
        return f"{num(lower)} < {symbol} < {num(upper)}"
    if lower is not None:
        return f"{symbol} > {num(lower)}"
    if upper is not None:
        return f"{symbol} < {num(upper)}"
    return str(solution)


# ──────────────────────────────────────────────────────────────
#  Root locus
# ──────────────────────────────────────────────────────────────

@dataclass
class RootLocusData:
    """Root locus data for varying gain K."""
    K_values:  np.ndarray
    roots:     np.ndarray      # shape (n_K, n_poles)  complex
    K_marginal: float          # gain at which locus crosses imaginary axis
    omega_marginal: float      # crossing frequency
    n_open_loop_poles: int
    n_open_loop_zeros: int
    # Asymptotes (for n_poles > n_zeros)
    asymptote_angles: list[float]   # degrees
    asymptote_centroid: float       # real part


def root_locus(
    G:     ctl.TransferFunction,
    K2:    ctl.TransferFunction | None = None,
    K_min: float = 0.0,
    K_max: float | None = None,
    n_pts: int = 400,
) -> RootLocusData:
    """
    Root locus of ``1 + K·L(s) = 0`` with ``L = K₂·G``, for K in [K_min, K_max].

    Branches are tracked by **continuity**, not by sorting. ``np.roots``
    returns roots in arbitrary order, so v1's ``np.sort_complex`` at each gain
    re-ordered them and produced branches that teleported between physical
    poles. Every branch was therefore discontinuous, which is why
    ``K_marginal`` came back ``nan`` for every system tested and Ziegler–
    Nichols could never find an ultimate gain.
    """
    if K2 is None:
        K2 = ctl.TransferFunction([1], [1])
    L = K2 * G

    if K_max is None:
        K_max = _estimate_max_K(L)

    K_values = np.linspace(K_min, K_max, n_pts)

    num_coeffs = np.atleast_1d(L.num[0][0])
    den_coeffs = np.atleast_1d(L.den[0][0])
    max_len = max(len(num_coeffs), len(den_coeffs))
    num_pad = np.pad(num_coeffs, (max_len - len(num_coeffs), 0))
    den_pad = np.pad(den_coeffs, (max_len - len(den_coeffs), 0))

    n_poles = max(len(den_pad) - 1, 0)
    roots = np.full((n_pts, n_poles), np.nan + 0j, dtype=complex)

    previous: np.ndarray | None = None
    for i, K in enumerate(K_values):
        char_poly = den_pad + K * num_pad
        rts = np.roots(char_poly)
        if len(rts) < n_poles:
            # A branch escaped to infinity (degree dropped): pad so the array
            # stays rectangular and the surviving branches keep their identity.
            rts = np.concatenate([rts, np.full(n_poles - len(rts),
                                               np.nan + 0j)])
        rts = _match_branches(previous, rts[:n_poles])
        roots[i] = rts
        previous = rts

    K_marginal, w_marginal = _find_marginal_gain(roots, K_values)
    # Prefer the exact imaginary-axis crossing when it can be found.
    exact = marginal_gain(L)
    if exact is not None:
        K_marginal, w_marginal = exact

    # Asymptotes
    poles_L = ctl.poles(L)
    zeros_L = ctl.zeros(L)
    n_p = len(poles_L)
    n_z = len(zeros_L)
    n_asym = n_p - n_z

    asym_angles = []
    asym_centroid = 0.0
    if n_asym > 0:
        centroid = (sum(p.real for p in poles_L) -
                    sum(z.real for z in zeros_L)) / n_asym
        asym_centroid = float(centroid)
        asym_angles = [(180.0 * (2 * k + 1)) / n_asym
                       for k in range(n_asym)]

    return RootLocusData(
        K_values=K_values, roots=roots,
        K_marginal=K_marginal, omega_marginal=w_marginal,
        n_open_loop_poles=n_p, n_open_loop_zeros=n_z,
        asymptote_angles=asym_angles, asymptote_centroid=asym_centroid,
    )


def _match_branches(previous: np.ndarray | None,
                    current: np.ndarray) -> np.ndarray:
    """
    Reorder ``current`` so each root continues the nearest branch of
    ``previous``.

    Uses optimal (Hungarian) assignment rather than greedy nearest-neighbour:
    where two branches approach a breakaway point, greedy matching assigns
    both to the same predecessor and the branches swap identity.
    """
    if previous is None:
        return np.asarray(current)

    prev = np.asarray(previous)
    cur = np.asarray(current)
    finite = np.isfinite(prev) & np.isfinite(cur)
    if not finite.any():
        return cur

    cost = np.abs(prev[:, None] - cur[None, :])
    cost = np.where(np.isfinite(cost), cost, 1e6)
    try:
        from scipy.optimize import linear_sum_assignment
        _, order = linear_sum_assignment(cost)
        return cur[order]
    except Exception:
        return cur


def marginal_gain(L: ctl.TransferFunction) -> tuple[float, float] | None:
    """
    Exact ``(K_u, ω_u)`` where ``1 + K·L(s)`` first has roots on the imaginary
    axis — the ultimate gain and frequency the Ziegler–Nichols oscillation
    method needs (ch.8, slide 37/44).

    Substituting ``s = jω`` into ``den(s) + K·num(s) = 0`` and splitting into
    real and imaginary parts gives two real polynomial equations in
    ``(K, ω)``; sympy solves them exactly. Returns ``None`` when the locus
    never crosses the axis for ``K > 0`` — a genuinely valid answer, which the
    caller should report rather than treat as a failure.
    """
    s, w, K = sp.symbols("s omega K", real=True)
    num = [sp.nsimplify(sp.Rational(repr(float(c)))) for c in np.atleast_1d(L.num[0][0])]
    den = [sp.nsimplify(sp.Rational(repr(float(c)))) for c in np.atleast_1d(L.den[0][0])]
    char = sp.Poly(den, s).as_expr() + K * sp.Poly(num, s).as_expr()

    expr = sp.expand(char.subs(s, sp.I * w))
    re_eq = sp.expand(sp.re(expr.rewrite(sp.cos)))
    im_eq = sp.expand(sp.im(expr.rewrite(sp.cos)))

    try:
        sols = sp.solve([sp.Eq(re_eq, 0), sp.Eq(im_eq, 0)], [K, w], dict=True)
    except Exception:
        return None

    best: tuple[float, float] | None = None
    for sol in sols:
        if K not in sol or w not in sol:
            continue
        try:
            k_val = complex(sol[K])
            w_val = complex(sol[w])
        except (TypeError, ValueError):
            continue
        if abs(k_val.imag) > 1e-9 or abs(w_val.imag) > 1e-9:
            continue
        k_val, w_val = k_val.real, abs(w_val.real)
        if k_val <= 1e-9 or w_val <= 1e-9:      # K ≤ 0 or the trivial ω = 0
            continue
        if best is None or k_val < best[0]:     # the *first* crossing
            best = (float(k_val), float(w_val))
    return best


def _estimate_max_K(L: ctl.TransferFunction) -> float:
    """
    A gain range wide enough to show the interesting part of the locus.

    Anchored on the marginal gain when one exists (so the imaginary-axis
    crossing is always on screen), otherwise on the open-loop pole spread.
    """
    marginal = marginal_gain(L)
    if marginal is not None:
        return float(marginal[0] * 2.5)
    try:
        poles = np.atleast_1d(ctl.poles(L))
        zeros = np.atleast_1d(ctl.zeros(L))
        spread = max([abs(p) for p in poles] + [abs(z) for z in zeros] + [1.0])
        order_excess = max(len(poles) - len(zeros), 1)
        return float(max(10.0 * spread ** order_excess, 10.0))
    except Exception:
        return 50.0


def _find_marginal_gain(
    roots: np.ndarray,
    K_values: np.ndarray,
) -> tuple[float, float]:
    """Find the K where a root first crosses the imaginary axis."""
    for i in range(1, len(K_values)):
        for j in range(roots.shape[1]):
            r_prev = roots[i - 1, j]
            r_curr = roots[i,     j]
            if r_prev.real < 0 <= r_curr.real:
                # Linear interpolation
                alpha = -r_prev.real / (r_curr.real - r_prev.real)
                K_marg = K_values[i - 1] + alpha * (K_values[i] - K_values[i - 1])
                w_marg = abs((r_prev + alpha * (r_curr - r_prev)).imag)
                return float(K_marg), float(w_marg)
    return float('nan'), float('nan')

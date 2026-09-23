"""
Exact block-diagram algebra over a :class:`~fakematlab.core.model.Model`.
========================================================================
Derives the transfer function between any two ports of any topology —
*exactly*, as a rational function, not as a sampled frequency response.

Why exact matters
-----------------
Routh, root locus, pole maps and the stability verdict all need polynomial
coefficients.  A frequency-sampled response cannot give them.  v1 worked
around this with hand-written formulas per (input, output) pair, six of which
were wrong and all of which silently assumed ``H = 1``.  This module derives
them from the drawn graph instead, so the picture and the mathematics can no
longer disagree.

Method
------
From the model's single rule ``y_i = H_i·(Σ_j A_ij y_j + b_i u)``::

    (I − diag(H)·A) · y = diag(H) · b

Writing ``H_i = N_i/D_i`` and multiplying row *i* by ``D_i`` clears every
denominator, leaving a **polynomial** matrix::

    M'_ij = D_i·δ_ij − N_i·A_ij          rhs'_i = N_i·b_i

``M'`` is solved over ℚ(s) with sympy, which is exact.  Coefficients are
converted float → ``Rational`` via their shortest decimal representation, so
``0.1`` becomes ``1/10`` rather than a 17-digit fraction.

The determinant ``det(M')`` is the **closed-loop characteristic polynomial of
the whole interconnection**, including modes that cancel out of every
individual I/O transfer function.  That is precisely what
:mod:`fakematlab.core.internal` needs to catch unstable pole/zero
cancellations (ch.6, slide 1/26).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

import control as ctl
import numpy as np
import sympy as sp

from .model import Edge, Model

S = sp.Symbol("s")

#: Solver results are memoised on ``Model.signature()``. Editing any
#: coefficient changes the signature and invalidates exactly the right
#: entries, so an unchanged model is re-analysed for free.
_CACHE: dict[tuple, object] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_LIMIT = 256


class IllPosedModelError(ValueError):
    """The interconnection has no unique solution (``det(M') ≡ 0``).

    Raised for a degenerate algebraic loop — e.g. a unity-gain positive
    feedback path with no dynamics anywhere in it.
    """


# ──────────────────────────────────────────────────────────────
#  Float → exact rational
# ──────────────────────────────────────────────────────────────

def _rat(x: float) -> sp.Rational:
    """
    Exact rational for a float, via its shortest round-tripping decimal.

    ``repr(0.1)`` is ``'0.1'`` so this yields ``1/10``, not the exact binary
    value ``3602879701896397/36028797018963968``.  Keeping denominators small
    keeps the determinants small.
    """
    r = sp.Rational(repr(float(x)))
    return r.limit_denominator(10 ** 12)


def _sym_poly(coeffs) -> sp.Expr:
    """Coefficient list (highest power first) → sympy polynomial in ``s``."""
    coeffs = [_rat(c) for c in np.atleast_1d(coeffs)]
    if not coeffs:
        return sp.Integer(0)
    return sp.Poly(coeffs, S).as_expr()


def _to_tf(expr: sp.Expr) -> ctl.TransferFunction:
    """Sympy rational function → :class:`control.TransferFunction`."""
    num_sym, den_sym = sp.fraction(sp.cancel(sp.together(expr)))
    num = _coeffs(num_sym)
    den = _coeffs(den_sym)
    if not den or all(abs(c) < 1e-300 for c in den):
        raise IllPosedModelError("derived transfer function has a zero denominator")
    # Normalise so the leading denominator coefficient is +1 — keeps the
    # displayed factored form stable and matches MATLAB's convention.
    lead = den[0]
    if lead != 0:
        num = [c / lead for c in num]
        den = [c / lead for c in den]
    return ctl.TransferFunction(num or [0.0], den)


def _coeffs(expr: sp.Expr) -> list[float]:
    """Sympy polynomial → float coefficient list (highest power first)."""
    p = sp.Poly(sp.expand(expr), S)
    return [float(c) for c in p.all_coeffs()]


# ──────────────────────────────────────────────────────────────
#  System assembly
# ──────────────────────────────────────────────────────────────

@dataclass
class _System:
    """The cleared-denominator polynomial system for one model."""
    ids:  list[str]
    idx:  dict[str, int]
    M:    sp.Matrix          # n×n polynomial matrix  M' = D·I − N·A
    Nvec: list[sp.Expr]      # numerator polynomial of each node


def _assemble(model: Model) -> _System:
    ids = model.node_ids
    idx = {nid: i for i, nid in enumerate(ids)}
    n = len(ids)

    # A[i][j] = summed gain of every edge j → i
    A = [[sp.Integer(0)] * n for _ in range(n)]
    for e in model.edges:
        A[idx[e.dst]][idx[e.src]] += _rat(e.gain)

    M = sp.zeros(n, n)
    Nvec: list[sp.Expr] = []
    for i, nid in enumerate(ids):
        node = model.node(nid)
        N, D = _sym_poly(node.num), _sym_poly(node.den)
        Nvec.append(N)
        for j in range(n):
            term = (D if i == j else sp.Integer(0)) - N * A[i][j]
            M[i, j] = sp.expand(term)
    return _System(ids, idx, M, Nvec)


def _cached(key: tuple, build):
    with _CACHE_LOCK:
        if key in _CACHE:
            return _CACHE[key]
    value = build()
    with _CACHE_LOCK:
        if len(_CACHE) >= _CACHE_LIMIT:
            _CACHE.clear()
        _CACHE[key] = value
    return value


def clear_cache() -> None:
    """Drop every memoised solve. Tests and benchmarks use this."""
    with _CACHE_LOCK:
        _CACHE.clear()


# ──────────────────────────────────────────────────────────────
#  Public API
# ──────────────────────────────────────────────────────────────

def transfer_matrix(model: Model, input_id: str) -> dict[str, ctl.TransferFunction]:
    """
    Every node's response to one input, from a single linear solve.

    Returns ``{node_id: TransferFunction}`` covering *all* nodes, not just
    declared outputs — the extra taps cost nothing and the Time tab uses them.
    """
    key = ("tmat", model.signature(), input_id)

    def build():
        sysm = _assemble(model)
        if input_id not in sysm.idx:
            raise KeyError(f"no node {input_id!r} in model")
        rhs = sp.zeros(len(sysm.ids), 1)
        rhs[sysm.idx[input_id]] = sysm.Nvec[sysm.idx[input_id]]
        try:
            y = sysm.M.LUsolve(rhs)
        except Exception as exc:  # singular → degenerate algebraic loop
            raise IllPosedModelError(
                f"model {model.name!r} has no unique solution for input "
                f"{input_id!r}; check for a gain-only feedback loop"
            ) from exc
        return {nid: _to_tf(y[i]) for nid, i in sysm.idx.items()}

    return _cached(key, build)


def transfer_function(model: Model, input_id: str,
                      output_id: str) -> ctl.TransferFunction:
    """
    Exact transfer function ``output_id / input_id`` for this topology.

    Works for any graph, loops and ``H ≠ 1`` included — the cases v1 got wrong.
    """
    mat = transfer_matrix(model, input_id)
    if output_id not in mat:
        raise KeyError(f"no node {output_id!r} in model")
    return mat[output_id]


def characteristic_polynomial(model: Model) -> np.ndarray:
    """
    Coefficients of ``det(M')`` — the characteristic polynomial of the whole
    interconnection, highest power first.

    Its roots are **all** closed-loop modes, including ones that cancel out of
    every individual transfer function.  Feed it to Routh, or to
    :func:`fakematlab.core.internal.internal_stability`.
    """
    key = ("chi", model.signature())

    def build():
        sysm = _assemble(model)
        det = sp.expand(sysm.M.det(method="berkowitz"))
        if det == 0:
            raise IllPosedModelError(
                f"model {model.name!r} is ill-posed: det(M') ≡ 0. "
                f"A feedback loop with no dynamics and unity gain does this."
            )
        coeffs = _coeffs(det)
        lead = coeffs[0]
        return np.array([c / lead for c in coeffs], dtype=float)

    return _cached(key, build)


def closed_loop_poles(model: Model) -> np.ndarray:
    """Roots of :func:`characteristic_polynomial` — every mode of the loop."""
    chi = characteristic_polynomial(model)
    if len(chi) <= 1:
        return np.array([], dtype=complex)
    return np.roots(chi)


def loop_transfer_function(model: Model, break_at: str) -> ctl.TransferFunction:
    """
    Loop transfer ``L(s)`` seen when the loop is broken at node ``break_at``.

    Cuts every edge *out of* ``break_at``, injects there, and measures what
    returns.  This is the general form of ``L = K₂·G·H`` and is what Nyquist,
    margins and root locus should analyse — derived from the graph rather than
    assumed.
    """
    cut = model.copy()
    probe = f"__probe__{break_at}"
    cut.add_wire(probe, label=f"probe({break_at})")
    # Re-route everything that left `break_at` so it leaves the probe instead,
    # leaving `break_at` as a pure measurement point fed only by the loop.
    rerouted = [
        Edge(probe, e.dst, e.gain) if e.src == break_at else e
        for e in cut.edges
    ]
    cut._edges = rerouted          # noqa: SLF001 — internal by design
    cut.add_input(probe)
    # Sign: L(s) is defined as the gain around the loop with the feedback sign
    # included, so what comes back to `break_at` already carries it.
    return -transfer_function(cut, probe, break_at)

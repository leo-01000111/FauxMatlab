"""
Structural properties: controllability, observability, Gramians, reduction.
===========================================================================
The questions a transfer function cannot answer. A plant may be perfectly
well-behaved on a Bode plot and still contain a mode no actuator can reach —
and if that mode is unstable, no controller of any kind will save it.

Rank versus the PBH test
------------------------
``rank(ctrb) = n`` is the textbook answer and the one to distrust numerically:
the controllability matrix is built from powers of ``A``, so its condition
number grows roughly like the spread of the eigenvalues raised to ``n``, and
for a well-conditioned system of order 8 it can already be numerically
singular. The **PBH test** — ``rank[A − λI, B] = n`` at each eigenvalue — asks
the same question one mode at a time, stays well conditioned, and says
*which* mode is the problem. Both are reported; PBH is the one believed.

No slycot
---------
``control.gram`` requires slycot, which needs a Fortran toolchain. The
Gramians here come from ``scipy.linalg.solve_continuous_lyapunov`` instead —
the same Lyapunov equation, twenty lines, no build step.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import control as ctl
import numpy as np
from scipy.linalg import solve_continuous_lyapunov, solve_discrete_lyapunov

from .statespace import StateSpaceError


@dataclass
class ModeTest:
    """The PBH verdict for one eigenvalue."""
    eigenvalue:    complex
    controllable:  bool
    observable:    bool
    stable:        bool
    ctrb_rank_deficiency: int
    obsv_rank_deficiency: int

    @property
    def fatal(self) -> bool:
        """An unstable mode that cannot be moved or cannot be seen."""
        return not self.stable and not (self.controllable and self.observable)

    def describe(self) -> str:
        bits = []
        if not self.controllable:
            bits.append("uncontrollable")
        if not self.observable:
            bits.append("unobservable")
        state = ", ".join(bits) if bits else "controllable and observable"
        return f"λ = {_fmt(self.eigenvalue)}: {state}"


@dataclass
class StructureReport:
    """Controllability and observability, overall and mode by mode."""
    n_states:      int
    ctrb:          np.ndarray
    obsv:          np.ndarray
    ctrb_rank:     int
    obsv_rank:     int
    controllable:  bool
    observable:    bool
    stabilizable:  bool
    detectable:    bool
    modes:         list[ModeTest]
    ctrb_condition: float
    obsv_condition: float
    notes:         list[str] = field(default_factory=list)

    @property
    def uncontrollable_modes(self) -> list[complex]:
        return [m.eigenvalue for m in self.modes if not m.controllable]

    @property
    def unobservable_modes(self) -> list[complex]:
        return [m.eigenvalue for m in self.modes if not m.observable]

    def summary(self) -> str:
        lines = [
            f"rank(ctrb) = {self.ctrb_rank}/{self.n_states}  "
            f"(cond {self.ctrb_condition:.3g})",
            f"rank(obsv) = {self.obsv_rank}/{self.n_states}  "
            f"(cond {self.obsv_condition:.3g})",
            f"controllable: {'yes' if self.controllable else 'NO'}    "
            f"observable: {'yes' if self.observable else 'NO'}",
            f"stabilizable: {'yes' if self.stabilizable else 'NO'}    "
            f"detectable:   {'yes' if self.detectable else 'NO'}",
        ]
        bad = [m for m in self.modes if not (m.controllable and m.observable)]
        if bad:
            lines.append("")
            lines.extend("  " + m.describe() for m in bad)
        lines.extend(f"⚠ {n}" for n in self.notes)
        return "\n".join(lines)


# ──────────────────────────────────────────────────────────────
#  Matrices and ranks
# ──────────────────────────────────────────────────────────────

def controllability_matrix(A, B) -> np.ndarray:
    """``[B  AB  A²B  …  Aⁿ⁻¹B]``."""
    A = np.atleast_2d(np.asarray(A, dtype=float))
    B = np.atleast_2d(np.asarray(B, dtype=float))
    return ctl.ctrb(A, B)


def observability_matrix(A, C) -> np.ndarray:
    """``[C; CA; CA²; …; CAⁿ⁻¹]``."""
    A = np.atleast_2d(np.asarray(A, dtype=float))
    C = np.atleast_2d(np.asarray(C, dtype=float))
    return ctl.obsv(A, C)


def analyse_structure(sys: ctl.StateSpace,
                      tol: float | None = None) -> StructureReport:
    """Full controllability/observability analysis, including PBH per mode."""
    A = np.atleast_2d(np.asarray(sys.A, dtype=float))
    B = np.atleast_2d(np.asarray(sys.B, dtype=float))
    C = np.atleast_2d(np.asarray(sys.C, dtype=float))
    n = A.shape[0]
    if n == 0:
        raise StateSpaceError("the system has no states to analyse")

    Wc = controllability_matrix(A, B)
    Wo = observability_matrix(A, C)
    ctrb_rank = int(np.linalg.matrix_rank(Wc, tol=tol))
    obsv_rank = int(np.linalg.matrix_rank(Wo, tol=tol))

    eigenvalues = np.linalg.eigvals(A)
    modes = [_pbh(A, B, C, lam, n, tol) for lam in eigenvalues]

    controllable = all(m.controllable for m in modes)
    observable = all(m.observable for m in modes)
    # Stabilizable: every *unstable* mode is controllable. Detectable: every
    # unstable mode is observable. Both are the weaker conditions that
    # actually matter — an uncontrollable but stable mode is harmless.
    stabilizable = all(m.controllable for m in modes if not m.stable)
    detectable = all(m.observable for m in modes if not m.stable)

    notes: list[str] = []
    cond_c = float(np.linalg.cond(Wc)) if Wc.size else float("inf")
    cond_o = float(np.linalg.cond(Wo)) if Wo.size else float("inf")
    if cond_c > 1e10 and controllable:
        notes.append(
            f"the controllability matrix is badly conditioned "
            f"({cond_c:.2g}); its rank is unreliable here, so the per-mode "
            f"PBH test above is the verdict to trust")
    if controllable != (ctrb_rank == n):
        notes.append(
            f"rank(ctrb) = {ctrb_rank} disagrees with the PBH test; "
            f"this is a numerical artefact of the rank computation")

    return StructureReport(
        n_states=n, ctrb=Wc, obsv=Wo,
        ctrb_rank=ctrb_rank, obsv_rank=obsv_rank,
        controllable=controllable, observable=observable,
        stabilizable=stabilizable, detectable=detectable,
        modes=modes, ctrb_condition=cond_c, obsv_condition=cond_o,
        notes=notes,
    )


def _pbh(A, B, C, lam, n, tol) -> ModeTest:
    """Popov–Belevitch–Hautus test at one eigenvalue."""
    eye = np.eye(n)
    ctrb_pencil = np.hstack([A - lam * eye, B.astype(complex)])
    obsv_pencil = np.vstack([A - lam * eye, C.astype(complex)])
    rc = int(np.linalg.matrix_rank(ctrb_pencil, tol=tol))
    ro = int(np.linalg.matrix_rank(obsv_pencil, tol=tol))
    return ModeTest(
        eigenvalue=complex(lam),
        controllable=rc == n, observable=ro == n,
        stable=bool(np.real(lam) < 0),
        ctrb_rank_deficiency=n - rc, obsv_rank_deficiency=n - ro,
    )


# ──────────────────────────────────────────────────────────────
#  Gramians and balancing
# ──────────────────────────────────────────────────────────────

def gramian(sys: ctl.StateSpace, which: str = "c") -> np.ndarray:
    """
    Controllability (``"c"``) or observability (``"o"``) Gramian.

    Solves the Lyapunov equation directly with scipy rather than through
    ``control.gram``, which needs slycot and therefore a Fortran toolchain.
    """
    A = np.atleast_2d(np.asarray(sys.A, dtype=float))
    B = np.atleast_2d(np.asarray(sys.B, dtype=float))
    C = np.atleast_2d(np.asarray(sys.C, dtype=float))

    if not np.all(np.real(np.linalg.eigvals(A)) < 0):
        raise StateSpaceError(
            "Gramians are only defined for a stable system: the integrals "
            "that define them do not converge otherwise.")

    discrete = getattr(sys, "dt", 0) not in (0, None)
    if which == "c":
        Q = B @ B.T
        return (solve_discrete_lyapunov(A, Q) if discrete
                else solve_continuous_lyapunov(A, -Q))
    if which == "o":
        Q = C.T @ C
        return (solve_discrete_lyapunov(A.T, Q) if discrete
                else solve_continuous_lyapunov(A.T, -Q))
    raise ValueError(f"which must be 'c' or 'o', got {which!r}")


def hankel_singular_values(sys: ctl.StateSpace) -> np.ndarray:
    """
    ``σᵢ = √λᵢ(Wc·Wo)``, largest first.

    Each one measures how much a state direction contributes to the
    input/output behaviour. A value near zero marks a state that can be
    deleted almost for free, which is what :func:`balanced_reduction` does.
    """
    Wc, Wo = gramian(sys, "c"), gramian(sys, "o")
    eigenvalues = np.linalg.eigvals(Wc @ Wo)
    return np.sqrt(np.abs(np.sort_complex(eigenvalues)[::-1].real))


def balanced_realization(sys: ctl.StateSpace) -> tuple[ctl.StateSpace, np.ndarray]:
    """
    Balance the system so ``Wc = Wo = diag(σ)``, returning ``(sys, σ)``.

    In balanced coordinates each state is equally hard to reach and easy to
    see, so "how important is this state" has a single answer.
    """
    Wc, Wo = gramian(sys, "c"), gramian(sys, "o")
    # Square-root balancing: numerically far better than forming Wc·Wo and
    # eigendecomposing it, which squares the condition number.
    #
    # The square roots come from a symmetric eigendecomposition rather than
    # Cholesky. A Gramian is only positive *semi*-definite, and Cholesky fails
    # outright on the semi-definite case; eigendecomposition handles it by
    # clipping the negative round-off.
    Lc, Lo = _psd_sqrt(Wc), _psd_sqrt(Wo)
    U, sigma, Vt = np.linalg.svd(Lo.T @ Lc)

    # A zero Hankel singular value means a state contributes nothing to the
    # input/output behaviour, and the transform below divides by √σ — so a
    # non-minimal realisation does not merely balance badly, it produces
    # nonsense.
    #
    # Minimality is decided by the staircase rank test rather than by
    # thresholding σ. A mode that cancels exactly still leaves σ at ~1e-9
    # rather than 0, which is far above machine epsilon and impossible to
    # separate from a genuinely small-but-real σ by magnitude alone.
    from .statespace import minimal as _minimal

    n_min = _minimal(sys).nstates
    if n_min < sys.nstates:
        raise StateSpaceError(
            f"cannot balance: this realisation is not minimal "
            f"({sys.nstates} states, only {n_min} reachable and observable). "
            f"Call statespace.minimal() first — balancing divides by √σ, and "
            f"for a redundant state σ is zero, so the transformation is "
            f"singular rather than merely ill-conditioned."
        )

    s_sqrt = np.diag(1.0 / np.sqrt(sigma))
    T = Lc @ Vt.T @ s_sqrt
    Ti = s_sqrt @ U.T @ Lo.T
    balanced = ctl.ss(Ti @ sys.A @ T, Ti @ sys.B, sys.C @ T, sys.D)
    return balanced, sigma


def _psd_sqrt(W: np.ndarray) -> np.ndarray:
    """
    A matrix ``L`` with ``L·Lᵀ = W``, for symmetric positive semi-definite ``W``.

    Eigenvalues that come back slightly negative are round-off on a zero and
    are clipped; a genuinely indefinite matrix is not a Gramian and would not
    reach here.
    """
    W = 0.5 * (W + W.T)                       # symmetrise away the round-off
    eigenvalues, vectors = np.linalg.eigh(W)
    return vectors @ np.diag(np.sqrt(np.maximum(eigenvalues, 0.0)))


def balanced_reduction(sys: ctl.StateSpace,
                       order: int) -> tuple[ctl.StateSpace, np.ndarray]:
    """
    Truncate a balanced realisation to ``order`` states.

    Returns the reduced model and the Hankel singular values. The error bound
    is ``‖G − Gᵣ‖∞ ≤ 2·Σ σᵢ`` over the discarded states, so the tail of the
    singular values tells you in advance what reduction will cost.
    """
    if order < 1 or order > sys.nstates:
        raise ValueError(
            f"order must be between 1 and {sys.nstates}, got {order}")
    balanced, sigma = balanced_realization(sys)
    k = order
    A = np.asarray(balanced.A)[:k, :k]
    B = np.asarray(balanced.B)[:k, :]
    C = np.asarray(balanced.C)[:, :k]
    return ctl.ss(A, B, C, balanced.D), sigma


def reduction_error_bound(sigma: np.ndarray, order: int) -> float:
    """``2·Σ σᵢ`` over the truncated states — the guaranteed ‖·‖∞ error."""
    return float(2.0 * np.sum(sigma[order:]))


# ──────────────────────────────────────────────────────────────
#  Kalman decomposition
# ──────────────────────────────────────────────────────────────

@dataclass
class KalmanDecomposition:
    """The four structural subspaces of a realisation."""
    n_controllable_observable:     int
    n_controllable_unobservable:   int
    n_uncontrollable_observable:   int
    n_uncontrollable_unobservable: int
    transform: np.ndarray

    @property
    def n_minimal(self) -> int:
        """Only the controllable *and* observable part reaches the transfer function."""
        return self.n_controllable_observable

    def summary(self) -> str:
        return (
            f"controllable & observable   : {self.n_controllable_observable}"
            f"   ← this is all the transfer function shows\n"
            f"controllable, unobservable  : {self.n_controllable_unobservable}\n"
            f"uncontrollable, observable  : {self.n_uncontrollable_observable}\n"
            f"uncontrollable, unobservable: "
            f"{self.n_uncontrollable_unobservable}"
        )


def kalman_decomposition(sys: ctl.StateSpace,
                         tol: float = 1e-9) -> KalmanDecomposition:
    """
    Split the state space into the four Kalman subspaces.

    Dimensions are obtained from the ranks of the controllability and
    observability matrices and of their intersection, which is enough to
    populate the table without needing the (numerically delicate) explicit
    basis.
    """
    A = np.atleast_2d(np.asarray(sys.A, dtype=float))
    B = np.atleast_2d(np.asarray(sys.B, dtype=float))
    C = np.atleast_2d(np.asarray(sys.C, dtype=float))
    n = A.shape[0]

    Wc = controllability_matrix(A, B)
    Wo = observability_matrix(A, C)
    n_c = int(np.linalg.matrix_rank(Wc, tol=tol))
    # The unobservable subspace is the null space of the observability matrix.
    n_o = int(np.linalg.matrix_rank(Wo, tol=tol))
    n_unobs = n - n_o

    controllable_basis = _range_basis(Wc, tol)
    unobservable_basis = _null_basis(Wo, tol)
    n_co_bar = _intersection_dim(controllable_basis, unobservable_basis, tol)

    return KalmanDecomposition(
        n_controllable_observable=n_c - n_co_bar,
        n_controllable_unobservable=n_co_bar,
        n_uncontrollable_observable=n - n_c - (n_unobs - n_co_bar),
        n_uncontrollable_unobservable=n_unobs - n_co_bar,
        transform=np.eye(n),
    )


def _range_basis(M: np.ndarray, tol: float) -> np.ndarray:
    if M.size == 0:
        return np.zeros((0, 0))
    U, s, _ = np.linalg.svd(M, full_matrices=False)
    return U[:, s > tol * max(s[0], 1.0)] if len(s) else U[:, :0]


def _null_basis(M: np.ndarray, tol: float) -> np.ndarray:
    if M.size == 0:
        return np.zeros((0, 0))
    _, s, Vt = np.linalg.svd(M, full_matrices=True)
    n = Vt.shape[0]
    padded = np.zeros(n)
    padded[:len(s)] = s
    return Vt[padded <= tol * max(padded[0], 1.0), :].T


def _intersection_dim(P: np.ndarray, Q: np.ndarray, tol: float) -> int:
    """Dimension of ``range(P) ∩ range(Q)``, via principal angles."""
    if P.size == 0 or Q.size == 0:
        return 0
    s = np.linalg.svd(P.T @ Q, compute_uv=False)
    return int(np.sum(s > 1.0 - 1e-6))


def _fmt(z: complex) -> str:
    if abs(z.imag) < 1e-10:
        return f"{z.real:.4g}"
    sign = "+" if z.imag >= 0 else "−"
    return f"{z.real:.4g} {sign} {abs(z.imag):.4g}j"

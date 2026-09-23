"""
State feedback: pole placement, LQR, and integral action.
=========================================================
``u = −Kx`` moves the closed-loop eigenvalues to ``eig(A − BK)``. If the pair
``(A, B)`` is controllable those eigenvalues can be put **anywhere**; if it is
only stabilizable, the uncontrollable ones stay where they are — which is why
:mod:`fakematlab.core.structural` runs first.

Placement or LQR?
-----------------
Pole placement asks *where* the poles go and says nothing about the cost of
getting them there — push them far left and the gains, and the control signal,
grow without limit. LQR asks instead what you are willing to pay: minimise
``∫ xᵀQx + uᵀRu``, and the poles land where that trade-off puts them. The
resulting loop also has guaranteed margins (≥ 6 dB gain, ≥ 60° phase) that
placement gives no claim to.

Both are provided; the Design tab shows the control effort alongside the
response for exactly this reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import control as ctl
import numpy as np
from scipy.linalg import solve_continuous_are, solve_discrete_are
from scipy.signal import place_poles as _scipy_place

from .statespace import StateSpaceError, state_space
from .structural import analyse_structure


class DesignError(ValueError):
    """The requested controller cannot be built."""


@dataclass
class FeedbackDesign:
    """A state-feedback gain and what it achieves."""
    K:              np.ndarray
    closed_loop:    ctl.StateSpace
    eigenvalues:    np.ndarray
    requested:      np.ndarray | None = None
    Nbar:           float = 1.0
    method:         str = ""
    cost_matrices:  tuple | None = None       # (Q, R) for LQR
    riccati:        np.ndarray | None = None  # P, for LQR
    notes:          list[str] = field(default_factory=list)

    @property
    def stable(self) -> bool:
        return bool(np.all(np.real(self.eigenvalues) < 0))

    def summary(self) -> str:
        lines = [
            f"{self.method}: K = {np.array2string(self.K, precision=4)}",
            f"closed-loop eigenvalues: "
            f"{np.array2string(self.eigenvalues, precision=4)}",
            f"Nbar (for unity DC gain) = {self.Nbar:.5g}",
        ]
        if self.requested is not None:
            error = np.max(np.abs(np.sort_complex(self.eigenvalues) -
                                  np.sort_complex(self.requested)))
            lines.append(f"placement error: {error:.3g}")
        lines.extend(f"⚠ {n}" for n in self.notes)
        return "\n".join(lines)


# ──────────────────────────────────────────────────────────────
#  Pole placement
# ──────────────────────────────────────────────────────────────

def place(sys: ctl.StateSpace, desired) -> FeedbackDesign:
    """
    Place the closed-loop eigenvalues at ``desired``.

    Uses the robust (Kautsky–Nichols) algorithm from scipy, which among the
    infinitely many gains achieving the same eigenvalues picks one whose
    eigenvectors are as well conditioned as possible — so the placement is
    less sensitive to model error than Ackermann's formula.
    """
    A, B = _matrices(sys)
    desired = np.atleast_1d(np.asarray(desired, dtype=complex))
    _check_request(sys, desired)

    try:
        result = _scipy_place(A, B, desired)
    except ValueError as exc:
        raise DesignError(
            f"pole placement failed: {exc}. Repeated poles cannot exceed the "
            f"number of inputs, and an uncontrollable mode cannot be moved at "
            f"all."
        ) from exc

    K = np.atleast_2d(result.gain_matrix)
    return _assemble(sys, K, "pole placement", requested=desired)


def acker(sys: ctl.StateSpace, desired) -> FeedbackDesign:
    """
    Ackermann's formula — the closed-form single-input answer.

    Included because it is what the course derives, and because comparing it
    with :func:`place` shows the point: both put the eigenvalues in the same
    place, but Ackermann inverts the controllability matrix, so on a
    higher-order system its gains visibly lose accuracy.
    """
    A, B = _matrices(sys)
    if B.shape[1] != 1:
        raise DesignError(
            f"Ackermann's formula is single-input only; this system has "
            f"{B.shape[1]} inputs. Use place() instead.")
    desired = np.atleast_1d(np.asarray(desired, dtype=complex))
    _check_request(sys, desired)

    K = np.atleast_2d(np.asarray(ctl.acker(A, B, desired), dtype=float))
    return _assemble(sys, K, "Ackermann", requested=desired)


def _check_request(sys, desired) -> None:
    n = sys.nstates
    if len(desired) != n:
        raise DesignError(
            f"give one desired eigenvalue per state: {n} needed, "
            f"{len(desired)} given")
    imag = desired[np.abs(desired.imag) > 1e-12]
    for lam in imag:
        if not np.any(np.abs(desired - np.conj(lam)) < 1e-9):
            raise DesignError(
                f"complex eigenvalue {lam} has no conjugate partner. A real "
                f"gain matrix can only produce conjugate pairs.")

    report = analyse_structure(sys)
    if not report.controllable:
        movable = [m for m in report.modes if not m.controllable]
        raise DesignError(
            f"the system is not controllable, so its eigenvalues cannot all "
            f"be placed. Fixed mode(s): "
            f"{', '.join(f'{m.eigenvalue:.4g}' for m in movable)}."
            + ("" if report.stabilizable else
               " It is not even stabilizable — no state feedback will make it "
               "stable.")
        )


# ──────────────────────────────────────────────────────────────
#  LQR
# ──────────────────────────────────────────────────────────────

def lqr(sys: ctl.StateSpace, Q=None, R=None) -> FeedbackDesign:
    """
    Linear quadratic regulator: minimise ``∫ xᵀQx + uᵀRu dt``.

    Solves the algebraic Riccati equation with scipy rather than
    ``control.lqr``, so the Riccati solution ``P`` and the cost matrices come
    back with the gain — the Design tab shows them, and ``xᵀPx`` is the
    optimal cost-to-go from any state.
    """
    A, B = _matrices(sys)
    n, m = A.shape[0], B.shape[1]
    Q = np.eye(n) if Q is None else _as_square(Q, n, "Q")
    R = np.eye(m) if R is None else _as_square(R, m, "R")

    if np.any(np.linalg.eigvalsh(_sym(Q)) < -1e-9):
        raise DesignError("Q must be positive semi-definite")
    if np.any(np.linalg.eigvalsh(_sym(R)) <= 0):
        raise DesignError(
            "R must be positive definite: a zero weight on some input means "
            "unlimited control effort is free, and the problem has no "
            "solution.")

    report = analyse_structure(sys)
    notes: list[str] = []
    if not report.stabilizable:
        raise DesignError(
            "the system is not stabilizable, so no finite-cost control "
            "exists. Unstable uncontrollable mode(s): "
            + ", ".join(f"{m.eigenvalue:.4g}"
                        for m in report.modes if m.fatal))
    if not report.controllable:
        notes.append(
            "some modes are uncontrollable but stable; they keep their "
            "open-loop eigenvalues")

    discrete = getattr(sys, "dt", 0) not in (0, None)
    try:
        P = (solve_discrete_are(A, B, Q, R) if discrete
             else solve_continuous_are(A, B, Q, R))
    except Exception as exc:
        raise DesignError(f"the Riccati equation could not be solved: {exc}"
                          ) from exc

    K = (np.linalg.solve(R + B.T @ P @ B, B.T @ P @ A) if discrete
         else np.linalg.solve(R, B.T @ P))

    design = _assemble(sys, np.atleast_2d(K), "LQR")
    design.cost_matrices = (Q, R)
    design.riccati = P
    design.notes.extend(notes)
    return design


def lqi(sys: ctl.StateSpace, Q=None, R=None) -> FeedbackDesign:
    """
    LQR with integral action on the tracking error.

    Augments the state with ``∫(r − y)dt`` and designs an LQR for the
    augmented plant. The integrator is what removes steady-state error under a
    constant disturbance — plain state feedback has no mechanism for that, and
    ``Nbar`` only corrects the nominal model.

    The returned ``K`` has one extra column: the gain on the integral state.
    """
    A, B, C = _matrices(sys, need_c=True)
    n, m = A.shape[0], B.shape[1]
    p = C.shape[0]

    # ẋ  = A x + B u
    # ξ̇ = r − y = −C x + r
    Aa = np.block([[A, np.zeros((n, p))],
                   [-C, np.zeros((p, p))]])
    Ba = np.vstack([B, np.zeros((p, m))])
    Ca = np.hstack([C, np.zeros((p, p))])

    augmented = state_space(Aa, Ba, Ca)
    Q = np.eye(n + p) if Q is None else _as_square(Q, n + p, "Q")
    design = lqr(augmented, Q, R)
    design.method = "LQI (LQR with integral action)"
    design.notes.append(
        f"state augmented with {p} integrator(s); the last {p} gain(s) act on "
        f"∫(r − y) dt")
    return design


# ──────────────────────────────────────────────────────────────
#  Closed loop and reference scaling
# ──────────────────────────────────────────────────────────────

def closed_loop(sys: ctl.StateSpace, K: np.ndarray,
                Nbar: float = 1.0) -> ctl.StateSpace:
    """``ẋ = (A − BK)x + B·Nbar·r``."""
    A, B, C = _matrices(sys, need_c=True)
    K = np.atleast_2d(np.asarray(K, dtype=float))
    if K.shape[1] != A.shape[0]:
        raise DesignError(
            f"K must have one column per state: {A.shape[0]} expected, "
            f"{K.shape[1]} given")
    D = np.atleast_2d(np.asarray(sys.D, dtype=float))
    return ctl.ss(A - B @ K, B * Nbar, C - D @ K, D * Nbar)


def reference_scaling(sys: ctl.StateSpace, K: np.ndarray) -> float:
    """
    ``Nbar`` making the closed-loop DC gain exactly 1.

    State feedback changes the DC gain as a side effect of moving the poles,
    so without this the output settles at the wrong value. It is a feedforward
    correction computed from the *nominal* model, so it removes steady-state
    error only as far as the model is right — unlike an integrator, which
    removes it regardless. :func:`lqi` is the robust alternative.
    """
    try:
        loop = closed_loop(sys, K, 1.0)
        dc = float(np.atleast_2d(ctl.dcgain(loop))[0, 0])
    except Exception:
        return 1.0
    if not np.isfinite(dc) or abs(dc) < 1e-12:
        return 1.0
    return float(1.0 / dc)


def control_effort(sys: ctl.StateSpace, K: np.ndarray, Nbar: float,
                   t: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Step response and the control signal that produces it.

    Returned together because the pair is the point: a placement that looks
    beautiful in ``y`` may be demanding a thousand units of ``u``.
    """
    A, B, C = _matrices(sys, need_c=True)
    K = np.atleast_2d(np.asarray(K, dtype=float))
    loop = ctl.ss(A - B @ K, B * Nbar, np.vstack([C, -K]),
                  np.vstack([np.zeros((C.shape[0], 1)),
                             np.atleast_2d(Nbar)]))
    _, response = ctl.step_response(loop, T=t)

    # For a multi-output system ``step_response`` returns
    # ``(n_outputs, n_inputs, n_time)``; with one input the middle axis is 1
    # and has to go, or each "curve" comes back as a (1, N) row that no
    # plotting call will accept.
    response = np.asarray(response)
    response = response.reshape(response.shape[0], -1)
    return response[0], response[-1]


# ──────────────────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────────────────

def _assemble(sys, K, method: str, requested=None) -> FeedbackDesign:
    Nbar = reference_scaling(sys, K)
    loop = closed_loop(sys, K, Nbar)
    return FeedbackDesign(
        K=K, closed_loop=loop,
        eigenvalues=np.atleast_1d(np.linalg.eigvals(np.asarray(loop.A))),
        requested=requested, Nbar=Nbar, method=method,
    )


def _matrices(sys, need_c: bool = False):
    A = np.atleast_2d(np.asarray(sys.A, dtype=float))
    B = np.atleast_2d(np.asarray(sys.B, dtype=float))
    if A.size == 0:
        raise StateSpaceError("the system has no states")
    if B.shape[0] != A.shape[0]:
        B = B.reshape(A.shape[0], -1)
    if need_c:
        C = np.atleast_2d(np.asarray(sys.C, dtype=float)).reshape(
            -1, A.shape[0])
        return A, B, C
    return A, B


def _as_square(M, n: int, name: str) -> np.ndarray:
    M = np.atleast_2d(np.asarray(M, dtype=float))
    if M.size == 1:
        return float(M.ravel()[0]) * np.eye(n)
    if M.shape == (1, n) or M.shape == (n, 1):
        return np.diag(M.ravel())
    if M.shape != (n, n):
        raise DesignError(
            f"{name} must be {n}×{n} (or a scalar, or {n} diagonal entries); "
            f"got {M.shape}")
    return M


def _sym(M: np.ndarray) -> np.ndarray:
    return 0.5 * (M + M.T)

"""
Observers: Luenberger, reduced-order, Kalman, and the separation principle.
===========================================================================
State feedback needs the state, and you measure ``y``, not ``x``. An observer
runs a copy of the plant driven by the measurement error::

    x̂̇ = A x̂ + B u + L(y − C x̂)

so the estimation error ``e = x − x̂`` obeys ``ė = (A − LC)e`` — it decays if
``A − LC`` is stable, whatever the input does.

Duality
-------
``(A − LC)ᵀ = Aᵀ − CᵀLᵀ``, which is a state-feedback problem for ``(Aᵀ, Cᵀ)``.
So observer design *is* controller design on the transposed system, and this
module is mostly a thin dual of :mod:`fakematlab.core.statefbk`. The same
duality maps controllability to observability, which is why a mode you cannot
see is a mode you cannot estimate.

The separation principle
------------------------
Combining a state feedback ``K`` with an observer ``L`` gives a closed loop
whose eigenvalues are exactly ``eig(A − BK) ∪ eig(A − LC)`` — the two designs
do not interact. :func:`verify_separation` checks that on the assembled
system rather than asserting it, because it is the kind of claim worth seeing
demonstrated.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import control as ctl
import numpy as np
from scipy.linalg import solve_continuous_are, solve_discrete_are

from .statefbk import DesignError, acker, place
from .statespace import StateSpaceError, state_space
from .structural import analyse_structure


@dataclass
class ObserverDesign:
    """An observer gain and what it achieves."""
    L:            np.ndarray
    eigenvalues:  np.ndarray            # of A − LC
    requested:    np.ndarray | None = None
    method:       str = ""
    covariances:  tuple | None = None   # (W, V) for a Kalman filter
    riccati:      np.ndarray | None = None
    notes:        list[str] = field(default_factory=list)

    @property
    def stable(self) -> bool:
        return bool(np.all(np.real(self.eigenvalues) < 0))

    def summary(self) -> str:
        lines = [
            f"{self.method}: L = {np.array2string(self.L, precision=4)}",
            f"estimation-error eigenvalues: "
            f"{np.array2string(self.eigenvalues, precision=4)}",
        ]
        lines.extend(f"⚠ {n}" for n in self.notes)
        return "\n".join(lines)


# ──────────────────────────────────────────────────────────────
#  Luenberger
# ──────────────────────────────────────────────────────────────

def observer(sys: ctl.StateSpace, desired, method: str = "place") -> ObserverDesign:
    """
    Luenberger observer placing ``eig(A − LC)`` at ``desired``.

    Rule of thumb: put the observer poles 2–5× faster than the controller's,
    so the estimate has settled before the feedback acts on it. Faster still
    and the observer amplifies measurement noise — which is the trade-off the
    Kalman filter makes explicitly instead of by eye.
    """
    A, C = _matrices(sys)
    dual = state_space(A.T, C.T, np.eye(A.shape[0]))

    report = analyse_structure(sys)
    if not report.observable:
        hidden = [m for m in report.modes if not m.observable]
        raise DesignError(
            f"the system is not observable, so its estimation-error "
            f"eigenvalues cannot all be placed. Hidden mode(s): "
            f"{', '.join(f'{m.eigenvalue:.4g}' for m in hidden)}."
            + ("" if report.detectable else
               " It is not even detectable — no observer will converge.")
        )

    design = (acker(dual, desired) if method == "acker"
              else place(dual, desired))
    L = np.atleast_2d(design.K).T
    return ObserverDesign(
        L=L,
        eigenvalues=np.atleast_1d(np.linalg.eigvals(A - L @ C)),
        requested=np.atleast_1d(np.asarray(desired, dtype=complex)),
        method=f"Luenberger observer ({method})",
    )


def kalman(sys: ctl.StateSpace, W=None, V=None) -> ObserverDesign:
    """
    Steady-state Kalman filter: the observer that minimises estimation
    variance given process noise ``W`` and measurement noise ``V``.

    The dual of :func:`fakematlab.core.statefbk.lqr`, and the same trade-off
    read the other way: a large ``V`` (noisy sensor) makes the filter trust
    its model and respond slowly, a large ``W`` (uncertain model) makes it
    trust the measurement and respond fast.
    """
    A, C = _matrices(sys)
    B = np.atleast_2d(np.asarray(sys.B, dtype=float))
    n, p = A.shape[0], C.shape[0]

    W = B @ B.T if W is None else _as_square(W, n, "W")
    V = np.eye(p) if V is None else _as_square(V, p, "V")

    if np.any(np.linalg.eigvalsh(_sym(V)) <= 0):
        raise DesignError(
            "V must be positive definite: zero measurement noise means the "
            "sensor is exact, and the optimal filter has infinite gain.")

    report = analyse_structure(sys)
    if not report.detectable:
        raise DesignError(
            "the system is not detectable, so the estimation error cannot be "
            "made to converge. Unstable hidden mode(s): "
            + ", ".join(f"{m.eigenvalue:.4g}"
                        for m in report.modes
                        if not m.observable and not m.stable))

    discrete = getattr(sys, "dt", 0) not in (0, None)
    try:
        # The filter Riccati equation is the control one on (Aᵀ, Cᵀ).
        P = (solve_discrete_are(A.T, C.T, W, V) if discrete
             else solve_continuous_are(A.T, C.T, W, V))
    except Exception as exc:
        raise DesignError(
            f"the filter Riccati equation could not be solved: {exc}") from exc

    L = (P @ C.T @ np.linalg.inv(C @ P @ C.T + V) if discrete
         else P @ C.T @ np.linalg.inv(V))

    design = ObserverDesign(
        L=np.atleast_2d(L),
        eigenvalues=np.atleast_1d(np.linalg.eigvals(A - L @ C)),
        method="Kalman filter", covariances=(W, V), riccati=P,
    )
    if not report.observable:
        design.notes.append(
            "some modes are unobservable but stable; their estimates decay to "
            "zero rather than converging to the true value")
    return design


def reduced_observer(sys: ctl.StateSpace, desired) -> ObserverDesign:
    """
    Reduced-order (Luenberger) observer: estimate only what is not measured.

    With ``p`` outputs, ``p`` states are already known exactly, so only
    ``n − p`` need estimating. The result is a smaller, faster observer — at
    the cost of feeding measurement noise straight through, since the measured
    states are used unfiltered.

    Requires ``C`` to have full row rank, which is what makes the measured
    part invertible.
    """
    A, C = _matrices(sys)
    n, p = A.shape[0], C.shape[0]
    if p >= n:
        raise DesignError(
            f"a reduced observer needs fewer outputs than states "
            f"({p} outputs, {n} states): there is nothing left to estimate")
    if np.linalg.matrix_rank(C) < p:
        raise DesignError(
            "C must have full row rank; two outputs measuring the same "
            "combination of states give no extra information")

    desired = np.atleast_1d(np.asarray(desired, dtype=complex))
    if len(desired) != n - p:
        raise DesignError(
            f"a reduced observer has {n - p} error eigenvalues, "
            f"{len(desired)} given")

    # Pick a complement of C so that T = [C; Cperp] is invertible, then
    # partition the transformed system into measured and unmeasured parts.
    _, _, Vt = np.linalg.svd(C)
    C_perp = Vt[p:, :]
    T = np.vstack([C, C_perp])
    Ti = np.linalg.inv(T)
    At = T @ A @ Ti

    # Only the unmeasured-state blocks are needed; the partition is
    # [[A11, A12], [A21, A22]] with the measured states on top.
    A12 = At[:p, p:]
    A22 = At[p:, p:]

    dual = state_space(A22.T, A12.T, np.eye(n - p))
    gain = place(dual, desired).K
    L = np.atleast_2d(gain).T

    return ObserverDesign(
        L=L,
        eigenvalues=np.atleast_1d(np.linalg.eigvals(A22 - L @ A12)),
        requested=desired,
        method=f"reduced-order observer ({n - p} of {n} states estimated)",
        notes=[f"{p} state(s) are measured directly and taken as exact"],
    )


# ──────────────────────────────────────────────────────────────
#  Observer-based compensator
# ──────────────────────────────────────────────────────────────

@dataclass
class Compensator:
    """A state feedback and an observer, assembled into one controller."""
    sys:              ctl.StateSpace      # the augmented closed loop
    controller:       ctl.StateSpace      # the compensator alone, y → u
    K:                np.ndarray
    L:                np.ndarray
    control_poles:    np.ndarray
    observer_poles:   np.ndarray
    closed_loop_poles: np.ndarray
    separation_holds: bool
    separation_error: float

    def summary(self) -> str:
        return "\n".join([
            f"controller poles: "
            f"{np.array2string(np.sort_complex(self.control_poles), precision=4)}",
            f"observer poles:   "
            f"{np.array2string(np.sort_complex(self.observer_poles), precision=4)}",
            f"closed loop:      "
            f"{np.array2string(np.sort_complex(self.closed_loop_poles), precision=4)}",
            f"separation principle holds: "
            f"{'yes' if self.separation_holds else 'NO'} "
            f"(max mismatch {self.separation_error:.3g})",
        ])


def compensator(sys: ctl.StateSpace, K: np.ndarray,
                L: np.ndarray) -> Compensator:
    """
    Assemble ``u = −Kx̂`` with an observer into a 2n-state closed loop.

    In the coordinates ``(x, e)`` the closed loop is block triangular::

        [ẋ]   [A − BK    BK  ] [x]
        [ė] = [   0    A − LC] [e]

    so its eigenvalues are the union of the two designs'. That is the
    separation principle, and :attr:`Compensator.separation_holds` checks it
    on the assembled matrices rather than taking it on trust.
    """
    A, C = _matrices(sys)
    B = np.atleast_2d(np.asarray(sys.B, dtype=float)).reshape(A.shape[0], -1)
    K = np.atleast_2d(np.asarray(K, dtype=float))
    L = np.atleast_2d(np.asarray(L, dtype=float))

    if K.shape[1] != A.shape[0]:
        raise DesignError(
            f"K must have {A.shape[0]} columns, got {K.shape[1]}")
    if L.shape[0] != A.shape[0]:
        raise DesignError(
            f"L must have {A.shape[0]} rows, got {L.shape[0]}")

    n = A.shape[0]
    full = np.block([[A - B @ K, B @ K],
                     [np.zeros((n, n)), A - L @ C]])
    augmented = ctl.ss(full, np.vstack([B, np.zeros((n, B.shape[1]))]),
                       np.hstack([C, np.zeros((C.shape[0], n))]),
                       np.zeros((C.shape[0], B.shape[1])))

    # The compensator on its own: input y, output u.
    controller = ctl.ss(A - B @ K - L @ C, L, -K,
                        np.zeros((K.shape[0], C.shape[0])))

    control_poles = np.linalg.eigvals(A - B @ K)
    observer_poles = np.linalg.eigvals(A - L @ C)
    closed = np.linalg.eigvals(full)

    expected = np.sort_complex(np.concatenate([control_poles, observer_poles]))
    error = float(np.max(np.abs(np.sort_complex(closed) - expected)))

    return Compensator(
        sys=augmented, controller=controller, K=K, L=L,
        control_poles=control_poles, observer_poles=observer_poles,
        closed_loop_poles=closed,
        separation_holds=error < 1e-6 * max(1.0, np.max(np.abs(expected))),
        separation_error=error,
    )


def estimation_error_response(sys: ctl.StateSpace, L: np.ndarray,
                              t: np.ndarray,
                              e0: np.ndarray | None = None) -> np.ndarray:
    """
    How an initial estimation error decays, one curve per state.

    Driven only by ``ė = (A − LC)e``: the input does not appear, which is the
    property that makes the observer usable at all.
    """
    A, C = _matrices(sys)
    L = np.atleast_2d(np.asarray(L, dtype=float))
    n = A.shape[0]
    e0 = np.ones(n) if e0 is None else np.asarray(e0, dtype=float).ravel()

    error_sys = ctl.ss(A - L @ C, np.zeros((n, 1)), np.eye(n),
                       np.zeros((n, 1)))
    _, response = ctl.initial_response(error_sys, T=t, X0=e0)
    return np.atleast_2d(response)


# ──────────────────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────────────────

def _matrices(sys):
    A = np.atleast_2d(np.asarray(sys.A, dtype=float))
    if A.size == 0:
        raise StateSpaceError("the system has no states")
    C = np.atleast_2d(np.asarray(sys.C, dtype=float)).reshape(-1, A.shape[0])
    return A, C


def _as_square(M, n: int, name: str) -> np.ndarray:
    M = np.atleast_2d(np.asarray(M, dtype=float))
    if M.size == 1:
        return float(M.ravel()[0]) * np.eye(n)
    if M.shape == (1, n) or M.shape == (n, 1):
        return np.diag(M.ravel())
    if M.shape != (n, n):
        raise DesignError(f"{name} must be {n}×{n}; got {M.shape}")
    return M


def _sym(M: np.ndarray) -> np.ndarray:
    return 0.5 * (M + M.T)

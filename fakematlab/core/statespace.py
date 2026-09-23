"""
State-space models: construction, conversion, canonical forms, modes.
=====================================================================
The entry point to the modern-control half (DYBAC). Everything here works on
:class:`control.StateSpace`; :mod:`fakematlab.core.structural` adds the
structural questions (controllability, observability) and
:mod:`fakematlab.core.statefbk` the design ones.

Modal decomposition
-------------------
The useful thing a state-space model offers over a transfer function is that
it shows *why* a response looks the way it does. Diagonalising ``A`` splits the
free response into independent modes ``e^{λᵢt}``, and the residues say how
strongly each one is excited by the input and seen at the output — which is
exactly the information a pole/zero plot hides when a mode nearly cancels.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import control as ctl
import numpy as np

from .tf_utils import PoleInfo, pole_info


class StateSpaceError(ValueError):
    """The state-space model is malformed or cannot be converted."""


# ──────────────────────────────────────────────────────────────
#  Construction and conversion
# ──────────────────────────────────────────────────────────────

def state_space(A, B, C, D=None) -> ctl.StateSpace:
    """Build a :class:`control.StateSpace`, checking the shapes agree."""
    A = np.atleast_2d(np.asarray(A, dtype=float))
    if A.shape[0] != A.shape[1]:
        raise StateSpaceError(
            f"A must be square; got {A.shape[0]}×{A.shape[1]}")
    n = A.shape[0]

    B = np.atleast_2d(np.asarray(B, dtype=float))
    if B.shape[0] != n:
        B = B.T if B.T.shape[0] == n else B
    if B.shape[0] != n:
        raise StateSpaceError(
            f"B must have {n} rows to match A; got {B.shape[0]}")

    C = np.atleast_2d(np.asarray(C, dtype=float))
    if C.shape[1] != n:
        C = C.T if C.T.shape[1] == n else C
    if C.shape[1] != n:
        raise StateSpaceError(
            f"C must have {n} columns to match A; got {C.shape[1]}")

    if D is None:
        D = np.zeros((C.shape[0], B.shape[1]))
    D = np.atleast_2d(np.asarray(D, dtype=float)).reshape(
        C.shape[0], B.shape[1])
    return ctl.ss(A, B, C, D)


def from_tf(tf: ctl.TransferFunction) -> ctl.StateSpace:
    """Transfer function → state space, in controllable canonical form."""
    return ctl.tf2ss(tf)


def to_tf(sys: ctl.StateSpace) -> ctl.TransferFunction:
    """State space → transfer function."""
    return ctl.ss2tf(sys)


def similarity_transform(sys: ctl.StateSpace, T: np.ndarray) -> ctl.StateSpace:
    """
    Change of state coordinates ``z = T⁻¹x``.

    The transfer function is invariant under this — which is the point: the
    same system has infinitely many state-space realisations, and choosing a
    good one is what the canonical forms below are for.
    """
    T = np.atleast_2d(np.asarray(T, dtype=float))
    if T.shape[0] != T.shape[1] or T.shape[0] != sys.nstates:
        raise StateSpaceError(
            f"T must be {sys.nstates}×{sys.nstates}; got {T.shape}")
    if abs(np.linalg.det(T)) < 1e-12:
        raise StateSpaceError(
            "T is singular, so it is not a change of coordinates")
    Ti = np.linalg.inv(T)
    return ctl.ss(Ti @ sys.A @ T, Ti @ sys.B, sys.C @ T, sys.D)


def controllable_form(sys: ctl.StateSpace) -> ctl.StateSpace:
    """Controllable (companion) canonical form."""
    return _canonical(sys, "reachable")


def observable_form(sys: ctl.StateSpace) -> ctl.StateSpace:
    """Observable canonical form."""
    return _canonical(sys, "observable")


def modal_form(sys: ctl.StateSpace) -> ctl.StateSpace:
    """
    Modal form: ``A`` block-diagonal, one block per mode.

    Real eigenvalues give 1×1 blocks and complex pairs give 2×2 blocks
    ``[[σ, ω], [−ω, σ]]``, so the states *are* the modes and the coupling
    between them is visible as exactly zero.

    Built from an eigendecomposition rather than ``control.canonical_form``,
    which routes the modal case through slycot's ``mb03rd`` and is therefore
    unavailable without a Fortran toolchain.
    """
    A = np.atleast_2d(np.asarray(sys.A, dtype=float))
    if A.size == 0:
        return sys

    eigenvalues, vectors = np.linalg.eig(A)
    columns: list[np.ndarray] = []
    used = np.zeros(len(eigenvalues), dtype=bool)

    for i, lam in enumerate(eigenvalues):
        if used[i]:
            continue
        if abs(lam.imag) < 1e-12:
            used[i] = True
            columns.append(np.real(vectors[:, i]))
            continue
        # A conjugate pair contributes the real and imaginary parts of one
        # eigenvector; together they span the same real 2-D invariant
        # subspace, and in that basis the block is a scaled rotation.
        partner = next(
            (j for j in range(i + 1, len(eigenvalues))
             if not used[j] and abs(eigenvalues[j] - np.conj(lam)) < 1e-9),
            None)
        if partner is None:
            raise StateSpaceError(
                f"eigenvalue {lam} has no conjugate partner, which cannot "
                f"happen for a real A — the matrix may be badly conditioned")
        used[i] = used[partner] = True
        columns.append(np.real(vectors[:, i]))
        columns.append(np.imag(vectors[:, i]))

    T = np.column_stack(columns)
    if abs(np.linalg.det(T)) < 1e-12:
        raise StateSpaceError(
            "A is defective (it has no eigenvector basis), so it cannot be "
            "put in modal form. A repeated eigenvalue with too few "
            "eigenvectors needs a Jordan form, which is not numerically "
            "computable."
        )
    return similarity_transform(sys, T)


def _canonical(sys: ctl.StateSpace, form: str) -> ctl.StateSpace:
    try:
        result = ctl.canonical_form(sys, form)
    except Exception as exc:
        raise StateSpaceError(
            f"could not compute the {form} form: {exc}. "
            f"A non-minimal or defective realisation often cannot be put in "
            f"canonical form; try minimal() first."
        ) from exc
    return result[0] if isinstance(result, tuple) else result


def minimal(sys: ctl.StateSpace, tol: float = 1e-9) -> ctl.StateSpace:
    """
    Smallest realisation with the same transfer function.

    Removes states that are uncontrollable or unobservable — the modes a
    transfer function cannot see. Comparing ``sys.nstates`` before and after
    is the quickest test of whether a realisation is minimal.

    Implemented here rather than via ``control.minreal``, which needs slycot
    (``tb01pd``) and therefore a Fortran toolchain. The method is the standard
    two-stage staircase: project onto the controllable subspace, then dualise
    and repeat for observability. Both stages use an **orthonormal** basis
    from an SVD, so the transformation is perfectly conditioned — unlike the
    obvious alternative of inverting a controllability matrix.
    """
    A = np.atleast_2d(np.asarray(sys.A, dtype=float))
    B = np.atleast_2d(np.asarray(sys.B, dtype=float))
    C = np.atleast_2d(np.asarray(sys.C, dtype=float))
    D = np.atleast_2d(np.asarray(sys.D, dtype=float))
    if A.size == 0:
        return sys

    A, B, C = _keep_controllable(A, B, C, tol)
    # Observability of (A, C) is controllability of (Aᵀ, Cᵀ), so the same
    # routine does both.
    if A.size:
        At, Ct, Bt = _keep_controllable(A.T, C.T, B.T, tol)
        A, B, C = At.T, Bt.T, Ct.T
    return ctl.ss(A, B, C, D)


def _keep_controllable(A, B, C, tol: float):
    """Project a realisation onto its controllable subspace."""
    n = A.shape[0]
    Wc = ctl.ctrb(A, B)
    U, s, _ = np.linalg.svd(Wc)
    rank = int(np.sum(s > tol * max(s[0], 1.0))) if len(s) else 0
    if rank == n:
        return A, B, C
    if rank == 0:
        return np.zeros((0, 0)), np.zeros((0, B.shape[1])), \
            np.zeros((C.shape[0], 0))
    # range(U[:, :rank]) is A-invariant and contains range(B), so in this
    # basis A is block upper triangular and the leading block is the
    # controllable part.
    T = U[:, :rank]
    return T.T @ A @ T, T.T @ B, C @ T


# ──────────────────────────────────────────────────────────────
#  Analysis
# ──────────────────────────────────────────────────────────────

@dataclass
class Mode:
    """One eigenvalue of ``A``, with how it couples to the input and output."""
    eigenvalue:   complex
    eigenvector:  np.ndarray
    info:         PoleInfo
    input_coupling:  float     # |left eigenvector · B|  — excitability
    output_coupling: float     # |C · right eigenvector| — visibility
    residue:      complex      # product of the two: contribution to C(sI−A)⁻¹B
    multiplicity: int = 1

    @property
    def visible(self) -> bool:
        """
        Whether this mode appears in the transfer function at all.

        A mode with no input coupling is uncontrollable; with no output
        coupling, unobservable. Either way the transfer function does not show
        it, which is exactly how an unstable mode hides (ch.6, 1/26).
        """
        return abs(self.residue) > 1e-9


@dataclass
class StateSpaceInfo:
    """Everything the State Space tab displays."""
    sys:        ctl.StateSpace
    n_states:   int
    n_inputs:   int
    n_outputs:  int
    eigenvalues: np.ndarray
    modes:      list[Mode]
    stable:     bool
    transmission_zeros: np.ndarray
    dc_gain:    float
    is_minimal: bool
    n_minimal:  int
    notes:      list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"{self.n_states} states, {self.n_inputs} input(s), "
            f"{self.n_outputs} output(s)",
            "stable" if self.stable else "UNSTABLE",
            f"minimal: {'yes' if self.is_minimal else f'no — {self.n_minimal} '
                                                      f'states suffice'}",
        ]
        lines.extend(f"⚠ {n}" for n in self.notes)
        return "\n".join(lines)


def analyse(sys: ctl.StateSpace) -> StateSpaceInfo:
    """Eigenvalues, modes, zeros and minimality of a state-space model."""
    A = np.atleast_2d(np.asarray(sys.A, dtype=float))
    B = np.atleast_2d(np.asarray(sys.B, dtype=float))
    C = np.atleast_2d(np.asarray(sys.C, dtype=float))

    eigenvalues, right = np.linalg.eig(A) if A.size else (np.zeros(0),
                                                          np.zeros((0, 0)))
    modes = _modes(A, B, C, eigenvalues, right)

    try:
        zeros = np.atleast_1d(ctl.zeros(sys))
    except Exception:
        zeros = np.zeros(0, dtype=complex)

    try:
        dc = float(np.atleast_2d(ctl.dcgain(sys))[0, 0])
    except Exception:
        dc = float("nan")

    n_min = sys.nstates
    notes: list[str] = []
    try:
        n_min = minimal(sys).nstates
    except StateSpaceError as exc:
        notes.append(str(exc))

    if n_min < sys.nstates:
        hidden = sys.nstates - n_min
        notes.append(
            f"{hidden} state{'s' if hidden != 1 else ''} cannot be seen from "
            f"the transfer function (uncontrollable or unobservable)")

    return StateSpaceInfo(
        sys=sys, n_states=sys.nstates, n_inputs=sys.ninputs,
        n_outputs=sys.noutputs,
        eigenvalues=eigenvalues, modes=modes,
        stable=bool(len(eigenvalues) == 0 or
                    np.all(np.real(eigenvalues) < 0)),
        transmission_zeros=zeros, dc_gain=dc,
        is_minimal=n_min == sys.nstates, n_minimal=n_min, notes=notes,
    )


def _modes(A, B, C, eigenvalues, right) -> list[Mode]:
    """
    Couple each eigenvalue to the input and output.

    The residue of mode *i* in ``C(sI−A)⁻¹B`` is ``(C vᵢ)(wᵢᵀ B)`` where
    ``vᵢ``/``wᵢ`` are the right/left eigenvectors normalised so ``wᵢᵀvᵢ = 1``.
    Its size says how much of the response that mode actually accounts for.
    """
    if len(eigenvalues) == 0:
        return []
    try:
        left = np.linalg.inv(right)          # rows are the left eigenvectors
    except np.linalg.LinAlgError:
        # A defective (non-diagonalisable) A has no eigenvector basis; report
        # the eigenvalues without couplings rather than failing outright.
        left = None

    out: list[Mode] = []
    for i, lam in enumerate(eigenvalues):
        v = right[:, i]
        if left is None:
            in_c = out_c = float("nan")
            residue = complex("nan")
        else:
            w = left[i, :]
            in_c = float(np.linalg.norm(w @ B))
            out_c = float(np.linalg.norm(C @ v))
            residue = complex(np.sum((C @ v) * (w @ B)))
        multiplicity = int(np.sum(np.abs(eigenvalues - lam) < 1e-9))
        out.append(Mode(
            eigenvalue=complex(lam), eigenvector=v,
            info=pole_info(complex(lam)),
            input_coupling=in_c, output_coupling=out_c,
            residue=residue, multiplicity=multiplicity,
        ))
    return out


# ──────────────────────────────────────────────────────────────
#  Per-mode response decomposition
# ──────────────────────────────────────────────────────────────

def modal_response(sys: ctl.StateSpace, t: np.ndarray,
                   x0: np.ndarray | None = None) -> dict[str, np.ndarray]:
    """
    Split the free response into one curve per mode.

    Returns ``{"total": y, "mode 0": y₀, …}`` where the modes sum to the
    total. Seeing which mode carries the slow tail is the fastest way to know
    which eigenvalue to move.
    """
    A = np.atleast_2d(np.asarray(sys.A, dtype=float))
    C = np.atleast_2d(np.asarray(sys.C, dtype=float))
    n = A.shape[0]
    if n == 0:
        return {"total": np.zeros_like(t)}

    if x0 is None:
        x0 = np.ones(n)
    x0 = np.asarray(x0, dtype=float).ravel()

    eigenvalues, right = np.linalg.eig(A)
    try:
        coeffs = np.linalg.solve(right, x0)
    except np.linalg.LinAlgError as exc:
        raise StateSpaceError(
            "A is defective (it has no eigenvector basis), so the response "
            "cannot be split into independent modes"
        ) from exc

    out: dict[str, np.ndarray] = {}
    total = np.zeros_like(t, dtype=float)
    for i, lam in enumerate(eigenvalues):
        contribution = np.real((C @ right[:, i]) * coeffs[i] *
                               np.exp(lam * t)).ravel()
        out[f"mode {i}  (λ={_fmt(lam)})"] = contribution
        total = total + contribution
    out["total"] = total
    return out


def _fmt(z: complex) -> str:
    if abs(z.imag) < 1e-10:
        return f"{z.real:.4g}"
    sign = "+" if z.imag >= 0 else "−"
    return f"{z.real:.3g}{sign}{abs(z.imag):.3g}j"

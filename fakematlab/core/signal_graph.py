"""
Numerical signal-flow solver — the independent oracle for :mod:`core.algebra`.
=============================================================================

.. note::
   For everyday work use :class:`fakematlab.core.model.Model` with
   :mod:`fakematlab.core.algebra`, which derives **exact** rational transfer
   functions (and hence poles, zeros, Routh tables and root loci).

   This module evaluates the same interconnection *numerically*, one frequency
   at a time, by a completely different route.  It is kept because that
   independence is valuable: the golden tests cross-check every exact result
   against it, so a mistake would have to be made identically twice to slip
   through.  It was the one part of v1 verified correct against hand-solved
   ground truth, which is why it earns the oracle role.

Nodes are TF blocks or summing junctions; edges are weighted connections.

The numerical solver evaluates any input→output transfer function at
arbitrary ω by solving a linear system in the frequency domain:

    y = H(A·y + b·u)  →  (I − H·A)·y = H·b·u
    T(jω) = eₖᵀ (I − H·A)⁻¹ H·b

This works for ANY directed topology — loops included — so the fixed
"course architecture" is just one instance of this class, and a future
free-form canvas only needs to build a different SignalGraph.

Public API
----------
graph = SignalGraph()
gid   = graph.add_block("G", tf)      # TF block
sid   = graph.add_sum("sum1")         # summing junction
graph.connect("r", "sum1", gain=+1)   # wire with gain
graph.add_external_input("r")         # declares r as an input port
graph.add_external_output("y")        # declares y as an output port
omega, H = graph.frequency_response(input_id="r", output_id="y")
"""

from __future__ import annotations

from dataclasses import dataclass, field

import control as ctl
import numpy as np

# ──────────────────────────────────────────────────────────────
#  Data structures
# ──────────────────────────────────────────────────────────────

@dataclass
class _Node:
    """One node (block or junction) in the signal-flow graph."""
    node_id: str
    label: str
    tf: ctl.TransferFunction | None  # None → summer (H=1, gains ±1 per edge)
    is_summer: bool = False             # True → output = sum of signed inputs
    metadata: dict = field(default_factory=dict)


@dataclass
class _Edge:
    """Directed connection from src_id → dst_id with a scalar gain."""
    src_id: str
    dst_id: str
    gain: float = 1.0  # +1 positive, −1 negative feedback


# ──────────────────────────────────────────────────────────────
#  Signal graph
# ──────────────────────────────────────────────────────────────

class SignalGraph:
    """
    Arbitrary directed signal-flow graph of LTI blocks.

    All analysis (time, frequency, stability) should be driven through
    this class so that swapping the fixed course architecture for a
    free-form user-drawn topology requires no changes to analysis code.
    """

    def __init__(self) -> None:
        self._nodes:   dict[str, _Node] = {}
        self._edges:   list[_Edge]      = []
        self._inputs:  set[str]         = set()   # external input ports
        self._outputs: set[str]         = set()   # external output ports

    # ── construction ────────────────────────────────────────────

    def add_block(self, node_id: str, tf: ctl.TransferFunction,
                  label: str | None = None, **meta) -> str:
        """Add a TF block. Returns node_id."""
        self._nodes[node_id] = _Node(
            node_id=node_id,
            label=label or node_id,
            tf=tf,
            is_summer=False,
            metadata=meta,
        )
        return node_id

    def add_sum(self, node_id: str, label: str | None = None) -> str:
        """Add a summing junction (output = signed sum of inputs). Returns node_id."""
        unity = ctl.TransferFunction([1], [1])
        self._nodes[node_id] = _Node(
            node_id=node_id,
            label=label or node_id,
            tf=unity,
            is_summer=True,
        )
        return node_id

    def add_wire(self, node_id: str, label: str | None = None) -> str:
        """Add a unity-gain wire node (useful as a named tap point)."""
        self._nodes[node_id] = _Node(
            node_id=node_id,
            label=label or node_id,
            tf=ctl.TransferFunction([1], [1]),
            is_summer=False,
        )
        return node_id

    def connect(self, src_id: str, dst_id: str, gain: float = 1.0) -> None:
        """Draw a directed edge from src → dst with the given gain sign."""
        self._edges.append(_Edge(src_id=src_id, dst_id=dst_id, gain=gain))

    def add_external_input(self, node_id: str) -> None:
        """Declare a node as an external input port (e.g. r, di, do, n)."""
        self._inputs.add(node_id)

    def add_external_output(self, node_id: str) -> None:
        """Declare a node as an external output port (e.g. y, u, e)."""
        self._outputs.add(node_id)

    def update_block_tf(self, node_id: str, tf: ctl.TransferFunction) -> None:
        """Replace the TF of an existing block (e.g. after user edits K2)."""
        if node_id not in self._nodes:
            raise KeyError(f"Node '{node_id}' not in graph")
        self._nodes[node_id].tf = tf

    # ── introspection ───────────────────────────────────────────

    @property
    def node_ids(self) -> list[str]:
        return list(self._nodes)

    @property
    def input_ids(self) -> list[str]:
        return sorted(self._inputs)

    @property
    def output_ids(self) -> list[str]:
        return sorted(self._outputs)

    def get_node(self, node_id: str) -> _Node:
        return self._nodes[node_id]

    def edges_into(self, node_id: str) -> list[_Edge]:
        return [e for e in self._edges if e.dst_id == node_id]

    def edges_from(self, node_id: str) -> list[_Edge]:
        return [e for e in self._edges if e.src_id == node_id]

    # ── frequency-domain solver ──────────────────────────────────

    def _ordered_nodes(self) -> list[str]:
        """Return stable ordering of all nodes (for matrix rows/cols)."""
        return list(self._nodes)

    def frequency_response(
        self,
        input_id:  str,
        output_id: str,
        omega: np.ndarray | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Compute complex frequency response T(jω) = output/input.

        Returns (omega, H) where H is a complex 1-D array.

        Algorithm: solve (I − H_diag · A)·y = H_diag·b·u at each ω.
        This handles algebraic loops only if they are resolvable (the
        matrix is non-singular) — degenerate loops are flagged.
        """
        if omega is None:
            omega = np.logspace(-3, 3, 500)

        ids   = self._ordered_nodes()
        n     = len(ids)
        idx   = {nid: i for i, nid in enumerate(ids)}

        # Build connection matrix A (n×n):  A[i,j] = sum of gains from j→i
        A = np.zeros((n, n), dtype=float)
        for edge in self._edges:
            if edge.src_id in idx and edge.dst_id in idx:
                A[idx[edge.dst_id], idx[edge.src_id]] += edge.gain

        # Build input vector b (n,):  b[i] = 1 if node i is the selected input
        b = np.zeros(n, dtype=float)
        if input_id in idx:
            b[idx[input_id]] = 1.0

        # Output index
        out_idx = idx[output_id]

        # Evaluate over omega
        H_resp = np.zeros(len(omega), dtype=complex)
        for k, w in enumerate(omega):
            jw = 1j * w
            # Build diagonal H matrix: H[i,i] = node_i TF evaluated at jw
            H_diag = np.zeros(n, dtype=complex)
            for nid, node in self._nodes.items():
                H_diag[idx[nid]] = self._eval_tf(node.tf, jw)

            # (I − H_diag · A)·y = H_diag·b
            M = np.eye(n, dtype=complex) - (H_diag[:, None] * A)
            rhs = H_diag * b  # element-wise
            try:
                y = np.linalg.solve(M, rhs)
                H_resp[k] = y[out_idx]
            except np.linalg.LinAlgError:
                H_resp[k] = np.nan

        return omega, H_resp

    @staticmethod
    def _eval_tf(tf: ctl.TransferFunction, s: complex) -> complex:
        """Evaluate a rational TF at a complex frequency s."""
        num = np.polyval(tf.num[0][0], s)
        den = np.polyval(tf.den[0][0], s)
        if abs(den) < 1e-300:
            return complex(1e30)
        return complex(num / den)

    def get_tf(
        self,
        input_id:  str,
        output_id: str,
        omega: np.ndarray | None = None,
        *,
        fit: bool = False,
    ) -> ctl.TransferFunction | tuple[np.ndarray, np.ndarray]:
        """
        Return the transfer function between input_id → output_id.

        Returns ``(omega, H_complex)`` — the raw frequency response from the
        matrix solver.

        There is deliberately no rational-fitting option: fitting a sampled
        response back to a transfer function is lossy and unnecessary now that
        :func:`fakematlab.core.algebra.transfer_function` derives the exact
        rational form directly from the graph.
        """
        if fit:
            raise NotImplementedError(
                "Rational fitting was removed — use "
                "fakematlab.core.algebra.transfer_function(model, inp, out) "
                "for an exact transfer function instead of fitting a sampled one."
            )
        return self.frequency_response(input_id, output_id, omega)

    # ── convenience: rebuild with new block TF ──────────────────

    def copy_with_update(self, node_id: str,
                         new_tf: ctl.TransferFunction) -> SignalGraph:
        """Return a shallow copy with one block's TF replaced."""
        g2 = SignalGraph()
        g2._nodes  = {k: v for k, v in self._nodes.items()}
        g2._edges  = list(self._edges)
        g2._inputs = set(self._inputs)
        g2._outputs = set(self._outputs)
        g2.update_block_tf(node_id, new_tf)
        return g2

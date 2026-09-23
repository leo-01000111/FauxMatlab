"""
The one graph type: a signal-flow model of LTI blocks.
======================================================
Every analysis in FakeMatlab is driven from a ``Model``.  The fixed course
architecture (ch.5 slide 16/24) is one instance of it; a user-drawn Simulink
topology is another.  Nothing downstream needs to know which.

Semantics (deliberately uniform — there is only one rule)
---------------------------------------------------------
Each node applies its transfer function to the **signed sum of its incoming
edges**, plus an external injection if it is declared an input port::

    y_i(s) = H_i(s) · ( Σ_j  A_ij · y_j(s)  +  b_i · u(s) )

``A_ij`` is the sum of the gains of every edge j → i, and ``b_i`` is 1 for the
selected input port and 0 elsewhere.  Summing junctions and plain wires are
just nodes whose ``H_i`` is 1 — they need no special case anywhere.

That single rule is what makes ``core.algebra`` able to derive an exact
transfer function for *any* topology, loops included.

Sign convention
---------------
Signs live on the **edges**, never inside a node.  A negative feedback path is
an edge with ``gain=-1``.  This is why the v1 bug class (a hand-written ``-S·K2``
that silently disagreed with the drawn diagram) cannot recur: the diagram and
the algebra read from the same edge list.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Iterable, Iterator, Literal

import control as ctl
import numpy as np

NodeKind = Literal["block", "sum", "wire"]


# ──────────────────────────────────────────────────────────────
#  Graph elements
# ──────────────────────────────────────────────────────────────

@dataclass
class Node:
    """
    One node of the signal-flow graph.

    ``kind`` is presentation metadata only — the solver treats every node
    identically.  It tells the canvas whether to draw a rectangle (``block``),
    a circle with ± signs (``sum``) or a bare tap point (``wire``).
    """
    node_id: str
    tf:      ctl.TransferFunction
    label:   str  = ""
    kind:    NodeKind = "block"
    meta:    dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.label:
            self.label = self.node_id

    # Coefficient access, normalised to plain Python lists so the node can be
    # hashed for the solver cache and serialised to JSON without numpy types.
    @property
    def num(self) -> list[float]:
        return [float(c) for c in np.atleast_1d(self.tf.num[0][0])]

    @property
    def den(self) -> list[float]:
        return [float(c) for c in np.atleast_1d(self.tf.den[0][0])]


@dataclass(frozen=True)
class Edge:
    """A directed connection ``src → dst`` carrying a scalar gain (usually ±1)."""
    src:  str
    dst:  str
    gain: float = 1.0


# ──────────────────────────────────────────────────────────────
#  Model
# ──────────────────────────────────────────────────────────────

class Model:
    """
    A directed graph of LTI nodes with declared input and output ports.

    Construction is deliberately blunt — build it, then hand it to
    :mod:`fakematlab.core.algebra`::

        m = Model("unity feedback")
        m.add_wire("r"); m.add_input("r")
        m.add_sum("sum", signs={"fb": "-"})
        m.add_block("G", ctl.tf([1], [1, 1]))
        m.add_wire("y"); m.add_output("y")
        m.connect("r", "sum").connect("sum", "G").connect("G", "y")
        m.connect("y", "sum", gain=-1)
    """

    def __init__(self, name: str = "model") -> None:
        self.name = name
        self._nodes:   dict[str, Node] = {}
        self._edges:   list[Edge]      = []
        self._inputs:  list[str]       = []
        self._outputs: list[str]       = []

    # ── construction ────────────────────────────────────────────

    def add_node(self, node: Node) -> "Model":
        if node.node_id in self._nodes:
            raise ValueError(f"duplicate node id {node.node_id!r}")
        self._nodes[node.node_id] = node
        return self

    def add_block(self, node_id: str, tf: ctl.TransferFunction,
                  label: str = "", **meta) -> "Model":
        """A transfer-function block (drawn as a rectangle)."""
        return self.add_node(Node(node_id, tf, label, "block", meta))

    def add_sum(self, node_id: str, label: str = "", **meta) -> "Model":
        """A summing junction. Signs live on the incoming edges, not here."""
        return self.add_node(Node(node_id, unity_tf(), label or "+", "sum", meta))

    def add_wire(self, node_id: str, label: str = "", **meta) -> "Model":
        """A named tap point — unity gain, exists so a signal can be observed."""
        return self.add_node(Node(node_id, unity_tf(), label, "wire", meta))

    def connect(self, src: str, dst: str, gain: float = 1.0) -> "Model":
        for nid in (src, dst):
            if nid not in self._nodes:
                raise KeyError(f"cannot connect: no node {nid!r}")
        self._edges.append(Edge(src, dst, float(gain)))
        return self

    def add_input(self, node_id: str) -> "Model":
        if node_id not in self._nodes:
            raise KeyError(f"no node {node_id!r}")
        if node_id not in self._inputs:
            self._inputs.append(node_id)
        return self

    def add_output(self, node_id: str) -> "Model":
        if node_id not in self._nodes:
            raise KeyError(f"no node {node_id!r}")
        if node_id not in self._outputs:
            self._outputs.append(node_id)
        return self

    # ── mutation ────────────────────────────────────────────────

    def set_tf(self, node_id: str, tf: ctl.TransferFunction) -> "Model":
        """Replace one node's transfer function (the common edit)."""
        if node_id not in self._nodes:
            raise KeyError(f"no node {node_id!r}. Have: {sorted(self._nodes)}")
        self._nodes[node_id] = replace(self._nodes[node_id], tf=tf)
        return self

    def with_tf(self, node_id: str, tf: ctl.TransferFunction) -> "Model":
        """Return a copy with one node's TF replaced — for sweeps and snapshots."""
        return self.copy().set_tf(node_id, tf)

    def copy(self) -> "Model":
        m = Model(self.name)
        m._nodes   = dict(self._nodes)
        m._edges   = list(self._edges)
        m._inputs  = list(self._inputs)
        m._outputs = list(self._outputs)
        return m

    # ── introspection ───────────────────────────────────────────

    @property
    def node_ids(self) -> list[str]:
        return list(self._nodes)

    @property
    def inputs(self) -> list[str]:
        return list(self._inputs)

    @property
    def outputs(self) -> list[str]:
        return list(self._outputs)

    @property
    def edges(self) -> list[Edge]:
        return list(self._edges)

    def node(self, node_id: str) -> Node:
        return self._nodes[node_id]

    def tf(self, node_id: str) -> ctl.TransferFunction:
        return self._nodes[node_id].tf

    def blocks(self) -> Iterator[Node]:
        """Nodes that carry real dynamics — what the block editor offers."""
        return (n for n in self._nodes.values() if n.kind == "block")

    def edges_into(self, node_id: str) -> list[Edge]:
        return [e for e in self._edges if e.dst == node_id]

    def edges_from(self, node_id: str) -> list[Edge]:
        return [e for e in self._edges if e.src == node_id]

    # ── caching key ─────────────────────────────────────────────

    def signature(self) -> tuple:
        """
        Hashable snapshot of everything the solver depends on.

        Used as the memo key in :mod:`fakematlab.core.algebra`, so repeated
        analysis of an unchanged model is free while a single edited
        coefficient invalidates exactly the right entries.
        """
        nodes = tuple(
            (n.node_id, tuple(n.num), tuple(n.den))
            for n in self._nodes.values()
        )
        edges = tuple((e.src, e.dst, e.gain) for e in self._edges)
        return (nodes, edges, tuple(self._inputs), tuple(self._outputs))

    def __repr__(self) -> str:
        return (f"<Model {self.name!r}: {len(self._nodes)} nodes, "
                f"{len(self._edges)} edges, in={self._inputs}, "
                f"out={self._outputs}>")


# ──────────────────────────────────────────────────────────────
#  Shared helper
# ──────────────────────────────────────────────────────────────

def unity_tf() -> ctl.TransferFunction:
    """TF = 1. Used for summing junctions and wires."""
    return ctl.TransferFunction([1.0], [1.0])

"""
Turn a :class:`~fakematlab.sim.model.SimModel` into something executable.
=========================================================================
Four passes:

1. **Width propagation** — iterate the per-block width rules to a fixed point,
   so ``Mux``/``Demux`` and vector signals resolve before anything runs.
2. **State layout** — assign every block a slice of the global continuous and
   discrete state vectors.
3. **Execution order** — topologically sort the blocks over **direct-feedthrough
   edges only**. A block whose output does not read its input can be evaluated
   from its state at any time, so it does not constrain the order — and, more
   usefully, it *breaks* what would otherwise be a cycle.
4. **Algebraic loops** — any cycle remaining in the feedthrough subgraph is an
   algebraic loop. It is reported with the exact cycle, and a minimal set of
   variables is chosen for the solver to iterate on.

Simulink reports algebraic loops as a wall of block names; naming the cycle in
order and suggesting the fix is most of what makes them tractable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .block import Block, BlockError
from .model import Connection, ModelError, PortRef, SimModel


class CompileError(ModelError):
    """The model cannot be turned into an executable form."""


# ──────────────────────────────────────────────────────────────
#  Compiled form
# ──────────────────────────────────────────────────────────────

@dataclass
class BlockPlan:
    """Everything the solver needs to know about one block."""
    block:        Block
    order:        int
    x_slice:      slice                 # into the global continuous state
    xd_slice:     slice                 # into the global discrete state
    input_conns:  list[Connection | None]
    input_widths: list[int]
    output_widths: list[int]
    feedthrough:  bool
    sample_time:  float


@dataclass
class CompiledModel:
    """A model prepared for simulation."""
    model:        SimModel
    plans:        dict[str, BlockPlan]
    order:        list[str]             # execution order
    n_states:     int
    n_dstates:    int
    sample_times: list[float]           # distinct positive sample times
    algebraic_loop: list[str] = field(default_factory=list)
    loop_breakers: list[str] = field(default_factory=list)
    warnings:     list[str] = field(default_factory=list)

    @property
    def has_algebraic_loop(self) -> bool:
        return bool(self.algebraic_loop)

    def initial_state(self) -> tuple[np.ndarray, np.ndarray]:
        x = np.zeros(self.n_states)
        xd = np.zeros(self.n_dstates)
        for plan in self.plans.values():
            if plan.block.n_states:
                x[plan.x_slice] = plan.block.initial_continuous_state()
            if plan.block.n_dstates:
                xd[plan.xd_slice] = plan.block.initial_discrete_state()
        return x, xd


# ──────────────────────────────────────────────────────────────
#  Compile
# ──────────────────────────────────────────────────────────────

def compile_model(model: SimModel) -> CompiledModel:
    """Prepare a model for simulation, or explain why it cannot be."""
    if len(model) == 0:
        raise CompileError("the model is empty — add some blocks first")

    warnings: list[str] = []
    model = flatten(model)
    widths = _propagate_widths(model, warnings)
    plans, n_states, n_dstates = _layout_states(model, widths)
    order, cycle = _execution_order(model, plans)

    breakers: list[str] = []
    if cycle:
        breakers = _choose_loop_breakers(model, cycle)
        order = _order_with_loop(model, plans, cycle)

    sample_times = sorted({
        p.sample_time for p in plans.values() if p.sample_time > 0
    })

    for ref in model.unconnected_inputs():
        warnings.append(f"{ref} is unconnected and will read zero")

    return CompiledModel(
        model=model, plans=plans, order=order,
        n_states=n_states, n_dstates=n_dstates,
        sample_times=sample_times,
        algebraic_loop=cycle, loop_breakers=breakers,
        warnings=warnings,
    )


# ── 0. flatten ─────────────────────────────────────────────────

#: A subsystem containing a subsystem containing… has to stop somewhere, and a
#: model that contains itself would otherwise expand forever.
MAX_NESTING = 32


def flatten(model: SimModel, _depth: int = 0) -> SimModel:
    """
    Splice every subsystem's contents into the parent, recursively.

    The returned model contains no ``Subsystem``, ``Inport`` or ``Outport``
    blocks: each subsystem's inner blocks are copied in with their ids
    prefixed, and the boundary ports are dissolved by reconnecting the wires
    that crossed them.

    Everything downstream — width propagation, execution order, algebraic-loop
    detection, state layout — therefore works on a flat graph. That is what
    lets the loop detector see a cycle that passes *through* a subsystem, which
    a recursive evaluator would miss.
    """
    if _depth > MAX_NESTING:
        raise CompileError(
            f"subsystems are nested more than {MAX_NESTING} deep — "
            f"a subsystem probably contains itself")

    subsystems = [b for b in model if b.type_name == "Subsystem"]
    if not subsystems:
        # Inside a subsystem the boundary ports are exactly what the caller
        # needs, so only the top level may complain about them.
        if _depth == 0:
            _check_stray_ports(model)
        return model

    flat = SimModel(model.name)
    for block in model:
        if block.type_name == "Subsystem":
            continue
        place = model.placement(block.block_id)
        flat.add_block(_clone(block), place.x, place.y)

    # How each subsystem boundary port dissolves into the inside.
    inward: dict[PortRef, list[PortRef]] = {}   # input  → inner consumers
    outward: dict[PortRef, PortRef] = {}        # output → inner producer
    sub_ids = {s.block_id for s in subsystems}

    for sub in subsystems:
        inner = flatten(sub.inner_model(), _depth + 1)
        prefix = f"{sub.block_id}/"

        for block in inner:
            if block.type_name in ("Inport", "Outport"):
                continue
            clone = _clone(block, new_id=prefix + block.block_id)
            place = inner.placement(block.block_id)
            flat.add_block(clone, place.x, place.y)

        inports = sub.inport_ids()
        outports = sub.outport_ids()

        for conn in inner.connections:
            src_is_port = inner.block(conn.src.block).type_name == "Inport"
            dst_is_port = inner.block(conn.dst.block).type_name == "Outport"
            if src_is_port or dst_is_port:
                continue
            flat.connect(f"{prefix}{conn.src.block}.{conn.src.port}",
                         f"{prefix}{conn.dst.block}.{conn.dst.port}")

        # An Inport's consumers become the destinations of whatever drove the
        # subsystem's matching outer input.
        for name, inner_id in inports.items():
            outer = PortRef(sub.block_id, name)
            targets = [
                PortRef(prefix + c.dst.block, c.dst.port)
                for c in inner.connections_from(
                    PortRef(inner_id, inner.block(inner_id).outputs[0]))
            ]
            inward[outer] = targets

        # An Outport's driver becomes the source of the subsystem's output.
        for name, inner_id in outports.items():
            outer = PortRef(sub.block_id, name)
            feeding = inner.connection_into(
                PortRef(inner_id, inner.block(inner_id).inputs[0]))
            if feeding is not None:
                outward[outer] = PortRef(prefix + feeding.src.block,
                                         feeding.src.port)

    # Re-route the wires that crossed a subsystem boundary.
    for conn in model.connections:
        # A wire *out of* a subsystem starts at whatever fed its Outport.
        if conn.src.block in sub_ids:
            if conn.src not in outward:
                continue                    # that Outport is not driven
            src = outward[conn.src]
        else:
            src = conn.src

        # A wire *into* a subsystem fans out to every consumer of its Inport.
        if conn.dst.block in sub_ids:
            for target in inward.get(conn.dst, []):
                flat.connect(f"{src.block}.{src.port}",
                             f"{target.block}.{target.port}")
            continue

        flat.connect(f"{src.block}.{src.port}",
                     f"{conn.dst.block}.{conn.dst.port}")

    if _depth == 0:
        _check_stray_ports(flat)
    return flat


def _clone(block, new_id: str | None = None):
    """A fresh instance of a block, optionally renamed."""
    from .block import create
    return create(block.type_name, new_id or block.block_id, **block.params)


def _check_stray_ports(model: SimModel) -> None:
    """An In/Outport outside a subsystem has nothing to connect to."""
    stray = [b.block_id for b in model
             if b.type_name in ("Inport", "Outport")]
    if stray:
        raise CompileError(
            f"{', '.join(stray)}: Inport and Outport define the boundary of a "
            f"subsystem, so they only mean something inside one. Put them in "
            f"a Subsystem block, or delete them."
        )


# ── 1. widths ──────────────────────────────────────────────────

def _propagate_widths(model: SimModel,
                      warnings: list[str]) -> dict[PortRef, int]:
    """
    Resolve every signal width by iterating the per-block rules.

    A single pass is not enough: a ``Demux`` downstream of a ``Mux`` only knows
    its output width once the ``Mux`` has resolved, and a feedback path can
    carry width information backwards. Iterating to a fixed point handles both
    without needing a dependency order — which we do not have yet at this
    stage, since ordering itself depends on nothing here.
    """
    widths: dict[PortRef, int] = {}
    for _ in range(len(model) + 2):
        changed = False
        for block in model:
            in_widths = []
            for port in block.inputs:
                conn = model.connection_into(PortRef(block.block_id, port))
                in_widths.append(widths.get(conn.src, 1) if conn else 1)
            try:
                out_widths = block.output_widths(in_widths)
            except BlockError as exc:
                raise CompileError(
                    f"{block.type_name} {block.block_id!r}: {exc}") from exc
            for port, width in zip(block.outputs, out_widths):
                ref = PortRef(block.block_id, port)
                if widths.get(ref) != width:
                    widths[ref] = width
                    changed = True
        if not changed:
            break
    else:
        warnings.append(
            "signal widths did not settle; check for a Mux/Demux loop")

    # Validate now that every width is known.
    for block in model:
        in_widths = []
        for port in block.inputs:
            conn = model.connection_into(PortRef(block.block_id, port))
            in_widths.append(widths.get(conn.src, 1) if conn else 1)
        try:
            block.validate_widths(in_widths)
        except BlockError as exc:
            raise CompileError(str(exc)) from exc
    return widths


# ── 2. state layout ────────────────────────────────────────────

def _layout_states(model: SimModel, widths: dict[PortRef, int]):
    plans: dict[str, BlockPlan] = {}
    x_at = xd_at = 0
    for block in model:
        n, nd = block.n_states, block.n_dstates
        in_conns, in_widths = [], []
        for port in block.inputs:
            conn = model.connection_into(PortRef(block.block_id, port))
            in_conns.append(conn)
            in_widths.append(widths.get(conn.src, 1) if conn else 1)
        out_widths = [widths[PortRef(block.block_id, p)] for p in block.outputs]

        plans[block.block_id] = BlockPlan(
            block=block, order=0,
            x_slice=slice(x_at, x_at + n),
            xd_slice=slice(xd_at, xd_at + nd),
            input_conns=in_conns, input_widths=in_widths,
            output_widths=out_widths,
            feedthrough=block.direct_feedthrough,
            sample_time=block.sample_time,
        )
        x_at += n
        xd_at += nd
    return plans, x_at, xd_at


# ── 3. execution order ─────────────────────────────────────────

def _feedthrough_edges(model: SimModel,
                       plans: dict[str, BlockPlan]) -> dict[str, set[str]]:
    """``{block: set of blocks that must be evaluated before it}``."""
    deps: dict[str, set[str]] = {bid: set() for bid in plans}
    for conn in model.connections:
        dst_plan = plans[conn.dst.block]
        if dst_plan.feedthrough:
            deps[conn.dst.block].add(conn.src.block)
    return deps


def _execution_order(model: SimModel, plans: dict[str, BlockPlan]):
    """Kahn's algorithm; whatever is left when it stalls is the cycle."""
    deps = _feedthrough_edges(model, plans)
    remaining = dict(deps)
    order: list[str] = []

    while remaining:
        ready = sorted(b for b, d in remaining.items()
                       if not (d & remaining.keys()))
        if not ready:
            return order, _find_cycle(remaining)
        for bid in ready:
            plans[bid].order = len(order)
            order.append(bid)
            del remaining[bid]
    return order, []


def _find_cycle(remaining: dict[str, set[str]]) -> list[str]:
    """
    One concrete cycle from the stalled subgraph, in traversal order.

    Reporting the actual path — ``Sum1 → Gain1 → Sum1`` — is what makes an
    algebraic loop fixable. A bare list of involved blocks leaves the user to
    work out which wire to cut.
    """
    nodes = set(remaining)
    colour: dict[str, int] = {}
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        colour[node] = 1
        stack.append(node)
        for dep in sorted(remaining.get(node, ())):
            if dep not in nodes:
                continue
            if colour.get(dep, 0) == 1:
                return stack[stack.index(dep):] + [dep]
            if colour.get(dep, 0) == 0:
                found = visit(dep)
                if found:
                    return found
        colour[node] = 2
        stack.pop()
        return None

    for node in sorted(nodes):
        if colour.get(node, 0) == 0:
            found = visit(node)
            if found:
                # The dependency edges point backwards (dep → node), so the
                # traversal reads in reverse signal-flow order. Flip it so the
                # message follows the wires.
                return list(reversed(found))
    return sorted(nodes)


def _choose_loop_breakers(model: SimModel, cycle: list[str]) -> list[str]:
    """
    A minimal set of blocks whose outputs the iterative solver will guess.

    One per cycle is enough: fixing any single signal in a loop makes the rest
    of it evaluable in order.
    """
    return [cycle[0]] if cycle else []


def _order_with_loop(model: SimModel, plans: dict[str, BlockPlan],
                     cycle: list[str]) -> list[str]:
    """
    An execution order that treats the loop breaker's output as given.

    Everything outside the loop keeps its topological position; the loop's
    members follow the cycle around from the breaker.
    """
    deps = _feedthrough_edges(model, plans)
    in_cycle = set(cycle)
    breaker = cycle[0]

    relaxed = {b: (d - {breaker} if b in in_cycle else d)
               for b, d in deps.items()}

    remaining = dict(relaxed)
    order: list[str] = []
    while remaining:
        ready = sorted(b for b, d in remaining.items()
                       if not (d & remaining.keys()))
        if not ready:
            # Still stuck: fall back to a stable arbitrary order so the solver
            # can at least attempt a fixed-point iteration.
            ready = sorted(remaining)
        for bid in ready:
            plans[bid].order = len(order)
            order.append(bid)
            remaining.pop(bid, None)
    return order


# ──────────────────────────────────────────────────────────────
#  Reporting
# ──────────────────────────────────────────────────────────────

def describe_algebraic_loop(compiled: CompiledModel) -> str:
    """A message that says what the loop is and how to break it."""
    if not compiled.has_algebraic_loop:
        return ""
    path = " → ".join(compiled.algebraic_loop)
    return (
        f"Algebraic loop: {path}\n"
        f"Every block in this cycle passes its input straight to its output, "
        f"so no block can be evaluated first. It will be solved numerically "
        f"at each step, which is slower and can fail to converge.\n"
        f"To remove it, break the cycle with a block that has no direct "
        f"feedthrough — a UnitDelay or ZeroOrderHold in a sampled loop, a "
        f"TransportDelay, or an Integrator if the physics allows one."
    )

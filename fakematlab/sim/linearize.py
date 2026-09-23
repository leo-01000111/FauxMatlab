"""
The bridge: a simulation model → a state-space model → the analysis tabs.
=========================================================================
This is what makes FakeMatlab one tool rather than two. Draw a loop on the
canvas, linearise it about an operating point, and the result lands in the
System / Frequency / Stability tabs as an ordinary transfer function — Bode,
Nyquist, Routh, root locus, margins, all of it.

Method
------
Central differences on the compiled model's own right-hand side::

    A = ∂f/∂x      B = ∂f/∂u
    C = ∂g/∂x      D = ∂g/∂u

evaluated at ``(x₀, u₀)``. Central rather than forward differences because the
error is then ``O(h²)`` instead of ``O(h)`` for the same number of evaluations
— and because a one-sided difference across a saturation corner silently
returns the slope of whichever side it happened to step into.

Nonlinearity is the whole reason this exists: a saturation block linearises to
a gain of 1 inside its limits and 0 outside, and the operating point decides
which. That is a feature — it is how you find out that your loop has no gain
left once the actuator is on its stop.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import control as ctl
import numpy as np

from .compile import CompiledModel, compile_model
from .model import PortRef, SimModel
from .solver import _Evaluator


class LinearizationError(RuntimeError):
    """The model could not be linearised as asked."""


@dataclass
class OperatingPoint:
    """Where the linearisation is taken."""
    t:  float = 0.0
    x:  np.ndarray = field(default_factory=lambda: np.zeros(0))
    xd: np.ndarray = field(default_factory=lambda: np.zeros(0))

    def describe(self) -> str:
        return (f"t = {self.t:g}, "
                f"x = {np.array2string(self.x, precision=4)}")


@dataclass
class LinearModel:
    """The result: a state-space model plus what it was taken around."""
    ss: ctl.StateSpace
    operating_point: OperatingPoint
    input_port: str
    output_port: str
    state_names: list[str]
    notes: list[str] = field(default_factory=list)

    def transfer_function(self) -> ctl.TransferFunction:
        """The same model as a transfer function, for the classical tabs."""
        return ctl.ss2tf(self.ss)

    def summary(self) -> str:
        poles = np.atleast_1d(ctl.poles(self.ss))
        lines = [
            f"Linearised {self.input_port} → {self.output_port} "
            f"about {self.operating_point.describe()}",
            f"  {self.ss.nstates} states, "
            f"poles: {np.array2string(poles, precision=4)}",
        ]
        lines.extend(f"  ⚠ {n}" for n in self.notes)
        return "\n".join(lines)


# ──────────────────────────────────────────────────────────────
#  Operating point
# ──────────────────────────────────────────────────────────────

def steady_state(model: SimModel | CompiledModel, t_settle: float = 50.0,
                 tol: float = 1e-6) -> OperatingPoint:
    """
    Find an operating point by running the model until it stops moving.

    Simpler and more robust than solving ``f(x) = 0`` directly: a trim solve
    needs a good initial guess and can converge onto an unstable equilibrium
    the system would never actually sit at. Simulating finds the one the model
    really settles into — and reports honestly when there isn't one.
    """
    from .solver import simulate

    compiled = model if isinstance(model, CompiledModel) else compile_model(model)
    if compiled.n_states == 0:
        return OperatingPoint(0.0, np.zeros(0), compiled.initial_state()[1])

    result = simulate(compiled, t_end=t_settle, n_points=400)
    if len(result.states) < 2:
        raise LinearizationError("the model produced no state trajectory")

    tail = result.states[-max(len(result.states) // 20, 2):]
    drift = float(np.max(np.abs(tail[-1] - tail[0])))
    scale = max(float(np.max(np.abs(tail[-1]))), 1.0)
    point = OperatingPoint(t=float(result.t[-1]), x=result.states[-1].copy(),
                           xd=compiled.initial_state()[1])
    if drift / scale > tol * 1e3:
        raise LinearizationError(
            f"the model has not settled after {t_settle:g} s "
            f"(states still moving by {drift:.3g}). Linearisation needs an "
            f"equilibrium — extend the settling time, or pick an operating "
            f"point explicitly."
        )
    return point


# ──────────────────────────────────────────────────────────────
#  Linearise
# ──────────────────────────────────────────────────────────────

def linearize(model: SimModel | CompiledModel,
              input_port: str,
              output_port: str,
              operating_point: OperatingPoint | None = None,
              step: float = 1e-6) -> LinearModel:
    """
    Linearise ``input_port → output_port`` about an operating point.

    Ports are named ``"block.port"``. The input port is an *input* of some
    block whose incoming wire is replaced by the perturbation; the output port
    is any block output.
    """
    compiled = model if isinstance(model, CompiledModel) else compile_model(model)
    if compiled.has_algebraic_loop:
        raise LinearizationError(
            "cannot linearise through an algebraic loop "
            f"({' → '.join(compiled.algebraic_loop)}); break it first"
        )

    in_ref = _resolve_input(compiled, input_port)
    out_ref = _resolve_output(compiled, output_port)

    if operating_point is None:
        x0, xd0 = compiled.initial_state()
        operating_point = OperatingPoint(0.0, x0, xd0)

    t0 = operating_point.t
    x0 = np.asarray(operating_point.x, dtype=float)
    xd0 = np.asarray(operating_point.xd, dtype=float)
    n = compiled.n_states

    ev = _Evaluator(compiled)

    def f_and_g(x: np.ndarray, u: float) -> tuple[np.ndarray, float]:
        """
        Derivatives and output for a perturbed state and input.

        The derivatives must be computed from the **same** input values the
        sweep used. Reading them back off the wires instead drops the
        perturbation whenever the driven port belongs to a block with states —
        so perturbing a transfer function's own input produced ``B = 0`` and a
        linearisation of exactly zero.
        """
        values, inputs = _sweep_with_override(
            ev, compiled, t0, x, xd0, {in_ref: np.array([u])})
        dx = _derivatives_from(compiled, t0, x, xd0, inputs) if n \
            else np.zeros(0)
        y = float(np.atleast_1d(values[out_ref])[0])
        return dx, y

    u0 = _nominal_input(ev, compiled, t0, x0, xd0, in_ref)

    A = np.zeros((n, n))
    C = np.zeros((1, n))
    for j in range(n):
        h = step * max(abs(x0[j]), 1.0)
        xp, xm = x0.copy(), x0.copy()
        xp[j] += h
        xm[j] -= h
        dxp, yp = f_and_g(xp, u0)
        dxm, ym = f_and_g(xm, u0)
        A[:, j] = (dxp - dxm) / (2 * h)
        C[0, j] = (yp - ym) / (2 * h)

    h = step * max(abs(u0), 1.0)
    dxp, yp = f_and_g(x0, u0 + h)
    dxm, ym = f_and_g(x0, u0 - h)
    B = ((dxp - dxm) / (2 * h)).reshape(n, 1)
    D = np.array([[(yp - ym) / (2 * h)]])

    notes = _notes(compiled, A, B, C, D)
    names = _state_names(compiled)
    return LinearModel(ss=ctl.ss(A, B, C, D),
                       operating_point=operating_point,
                       input_port=str(in_ref), output_port=str(out_ref),
                       state_names=names, notes=notes)


def _sweep_with_override(ev, compiled, t, x, xd, override):
    """
    Evaluate every block with one input port pinned to a given value.

    Returns ``(port values, {block_id: input list})``. The second item is the
    important one: it is what each block *actually received*, which is what
    the derivatives must be computed from.
    """
    values: dict[PortRef, np.ndarray] = dict(override)

    def gather(bid: str) -> list[np.ndarray]:
        plan = compiled.plans[bid]
        inputs = []
        for port, conn, width in zip(plan.block.inputs, plan.input_conns,
                                     plan.input_widths):
            ref = PortRef(bid, port)
            if ref in override:
                inputs.append(override[ref])
            elif conn is None:
                inputs.append(np.zeros(width))
            else:
                inputs.append(values.get(conn.src, np.zeros(width)))
        return inputs

    for bid in compiled.order:
        plan = compiled.plans[bid]
        outs = plan.block.output(t, x[plan.x_slice], xd[plan.xd_slice],
                                 gather(bid))
        for port, value in zip(plan.block.outputs, outs):
            values[PortRef(bid, port)] = np.atleast_1d(
                np.asarray(value, dtype=float))

    # Gather the inputs again, now that every output is known.
    #
    # A block without direct feedthrough is ordered *early* — its output needs
    # only its state — so when the sweep reached it, its upstream blocks had
    # not run yet and its inputs read as zero. Those inputs do not affect its
    # output, but they are exactly what ``derivative()`` needs, so capturing
    # them during the sweep produced B = 0 for every state block fed from
    # upstream.
    inputs_by_block = {bid: gather(bid) for bid in compiled.plans}
    return values, inputs_by_block


def _derivatives_from(compiled, t, x, xd, inputs_by_block) -> np.ndarray:
    """``dx/dt`` using the input values each block was actually given."""
    dx = np.zeros(compiled.n_states)
    for bid, plan in compiled.plans.items():
        if not plan.block.n_states:
            continue
        dx[plan.x_slice] = plan.block.derivative(
            t, x[plan.x_slice], xd[plan.xd_slice], inputs_by_block[bid])
    return dx


def _nominal_input(ev, compiled, t, x, xd, in_ref) -> float:
    """The value already arriving at the perturbed input port."""
    values, _ = _sweep_with_override(ev, compiled, t, x, xd, {})
    plan = compiled.plans[in_ref.block]
    idx = plan.block.inputs.index(in_ref.port)
    conn = plan.input_conns[idx]
    if conn is None:
        return 0.0
    return float(np.atleast_1d(values.get(conn.src, np.zeros(1)))[0])


def _resolve_input(compiled, spec: str) -> PortRef:
    block_id, _, port = spec.partition(".")
    plan = compiled.plans.get(block_id)
    if plan is None:
        raise LinearizationError(
            f"no block {block_id!r}; have "
            f"{', '.join(sorted(compiled.plans))}")
    ports = plan.block.inputs
    if not port:
        if len(ports) != 1:
            raise LinearizationError(
                f"{block_id} has {len(ports)} input ports; name one, "
                f"e.g. '{block_id}.{ports[0] if ports else 'in'}'")
        port = ports[0]
    if port not in ports:
        raise LinearizationError(
            f"{block_id} has no input port {port!r}; "
            f"valid: {', '.join(ports)}")
    return PortRef(block_id, port)


def _resolve_output(compiled, spec: str) -> PortRef:
    block_id, _, port = spec.partition(".")
    plan = compiled.plans.get(block_id)
    if plan is None:
        raise LinearizationError(
            f"no block {block_id!r}; have "
            f"{', '.join(sorted(compiled.plans))}")
    ports = plan.block.outputs
    if not port:
        if len(ports) != 1:
            raise LinearizationError(
                f"{block_id} has {len(ports)} output ports; name one")
        port = ports[0]
    if port not in ports:
        raise LinearizationError(
            f"{block_id} has no output port {port!r}; "
            f"valid: {', '.join(ports)}")
    return PortRef(block_id, port)


def _state_names(compiled) -> list[str]:
    names: list[str] = []
    for bid, plan in compiled.plans.items():
        for i in range(plan.block.n_states):
            names.append(f"{bid}[{i}]")
    return names


def _notes(compiled, A, B, C, D) -> list[str]:
    notes: list[str] = []
    if np.allclose(B, 0.0) and np.allclose(D, 0.0):
        notes.append(
            "the input has no effect at this operating point — it may be "
            "blocked by a saturated block or a dead zone")
    if np.allclose(C, 0.0) and np.allclose(D, 0.0):
        notes.append("the output does not respond to any state here")
    if compiled.sample_times:
        notes.append(
            f"discrete blocks (sample times "
            f"{', '.join(f'{t:g}s' for t in compiled.sample_times)}) are "
            f"held fixed; this is the continuous part of the model only")
    return notes

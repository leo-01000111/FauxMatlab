"""
The simulation engine.
======================

Structure of a run
------------------
The timeline is cut at every **sample hit** — the union of all discrete blocks'
sample times. Between two hits nothing discrete changes, so that span is a
plain continuous ODE and any solver can take it. At each hit the discrete
blocks update, and integration restarts from the new state.

That is what lets a 50 Hz controller drive a continuous plant: the ODE solver
is *forced to land* on 0.02, 0.04, 0.06 … instead of stepping over them with
whatever stride its error estimate happens to like.
``control.interconnect`` cannot express this at all — it rejects mixed
timebases outright — which is why this engine exists.

Within a span
-------------
* Block outputs are evaluated in the compiled order. Non-feedthrough blocks
  read only their state, so they are always ready.
* An algebraic loop is closed with ``scipy.optimize.fsolve`` on the breaker's
  output.
* Discontinuities are caught by :meth:`~fakematlab.sim.block.Block.zero_crossings`
  events, so a saturation limit or relay switch is hit exactly.
"""

from __future__ import annotations

import warnings as _warnings
from dataclasses import dataclass, field

import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import fsolve

from .compile import CompiledModel, compile_model, describe_algebraic_loop
from .model import PortRef, SimModel

#: Solvers offered in the UI. Fixed-step ones are handled separately.
VARIABLE_STEP = {"RK45", "LSODA", "Radau", "BDF", "DOP853"}
FIXED_STEP = {"ode1", "ode4"}


class SimulationError(RuntimeError):
    """The run could not be completed."""


@dataclass
class SimResult:
    """Everything a run produced."""
    t:        np.ndarray
    signals:  dict[str, np.ndarray]        # "block.port" → (n_time, width)
    states:   np.ndarray                   # (n_time, n_states)
    scopes:   dict[str, list[str]] = field(default_factory=dict)
    workspace: dict[str, np.ndarray] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    solver:   str = ""
    n_steps:  int = 0

    def signal(self, name: str) -> np.ndarray:
        """One logged signal, as ``(n_time, width)``."""
        if name in self.signals:
            return self.signals[name]
        matches = [k for k in self.signals if k.startswith(name + ".")]
        if len(matches) == 1:
            return self.signals[matches[0]]
        raise KeyError(
            f"no signal {name!r}. Available: {', '.join(sorted(self.signals))}"
        )

    def trace(self, name: str, channel: int = 0) -> np.ndarray:
        """One scalar channel of a logged signal."""
        return self.signal(name)[:, channel]


# ──────────────────────────────────────────────────────────────
#  Evaluator
# ──────────────────────────────────────────────────────────────

class _Evaluator:
    """Evaluates every block output at one instant, given the state."""

    def __init__(self, compiled: CompiledModel) -> None:
        self.c = compiled
        self._values: dict[PortRef, np.ndarray] = {}

    def _inputs(self, plan) -> list[np.ndarray]:
        out = []
        for conn, width in zip(plan.input_conns, plan.input_widths):
            if conn is None:
                out.append(np.zeros(width))
            else:
                out.append(self._values.get(conn.src, np.zeros(width)))
        return out

    def evaluate(self, t: float, x: np.ndarray,
                 xd: np.ndarray) -> dict[PortRef, np.ndarray]:
        """All port values at ``t``, resolving any algebraic loop."""
        if self.c.has_algebraic_loop:
            return self._evaluate_with_loop(t, x, xd)
        return self._sweep(t, x, xd)

    def _sweep(self, t, x, xd, seed=None) -> dict[PortRef, np.ndarray]:
        self._values = dict(seed) if seed else {}
        for bid in self.c.order:
            plan = self.c.plans[bid]
            block = plan.block
            outs = block.output(t, x[plan.x_slice], xd[plan.xd_slice],
                                self._inputs(plan))
            for port, value in zip(block.outputs, outs):
                ref = PortRef(bid, port)
                if seed is None or ref not in self._values:
                    self._values[ref] = np.atleast_1d(np.asarray(value,
                                                                 dtype=float))
        return self._values

    def _evaluate_with_loop(self, t, x, xd) -> dict[PortRef, np.ndarray]:
        """
        Close the algebraic loop by solving for the breaker's output.

        Guess the breaker's output, sweep the model once, and compare the
        breaker's recomputed output with the guess. The root of that residual
        is the consistent solution.
        """
        breaker_id = self.c.loop_breakers[0]
        plan = self.c.plans[breaker_id]
        refs = [PortRef(breaker_id, p) for p in plan.block.outputs]
        widths = plan.output_widths
        guess = np.concatenate([
            self._values.get(r, np.zeros(w)) for r, w in zip(refs, widths)
        ]) if self._values else np.zeros(int(sum(widths)))

        def residual(flat: np.ndarray) -> np.ndarray:
            seed, at = {}, 0
            for ref, w in zip(refs, widths):
                seed[ref] = flat[at:at + w]
                at += w
            values = self._sweep(t, x, xd, seed=seed)
            recomputed = plan.block.output(
                t, x[plan.x_slice], xd[plan.xd_slice],
                self._loop_inputs(plan, values))
            return np.concatenate([np.atleast_1d(v) for v in recomputed]) - flat

        def _loop_inputs(p, values):
            return [values.get(c.src, np.zeros(w)) if c is not None
                    else np.zeros(w)
                    for c, w in zip(p.input_conns, p.input_widths)]

        self._loop_inputs = _loop_inputs            # bound for residual()
        with _warnings.catch_warnings():
            _warnings.simplefilter("ignore")
            solution, _info, ok, msg = fsolve(residual, guess, full_output=True)
        if ok != 1:
            raise SimulationError(
                f"the algebraic loop through "
                f"{' → '.join(self.c.algebraic_loop)} did not converge at "
                f"t = {t:.6g} ({msg.strip()}). "
                f"Break it with a UnitDelay or another block without direct "
                f"feedthrough."
            )
        seed, at = {}, 0
        for ref, w in zip(refs, widths):
            seed[ref] = solution[at:at + w]
            at += w
        return self._sweep(t, x, xd, seed=seed)

    # ── derived quantities ──────────────────────────────────────

    def derivatives(self, t, x, xd, values) -> np.ndarray:
        dx = np.zeros(self.c.n_states)
        for _bid, plan in self.c.plans.items():
            if not plan.block.n_states:
                continue
            self._values = values
            dx[plan.x_slice] = plan.block.derivative(
                t, x[plan.x_slice], xd[plan.xd_slice], self._inputs(plan))
        return dx

    def zero_crossings(self, t, x, xd, values) -> np.ndarray:
        out = []
        for _bid, plan in self.c.plans.items():
            self._values = values
            zc = plan.block.zero_crossings(
                t, x[plan.x_slice], xd[plan.xd_slice], self._inputs(plan))
            if len(zc):
                out.append(np.atleast_1d(zc))
        return np.concatenate(out) if out else np.zeros(0)

    def update_discrete(self, t, x, xd, values, due: set[str]) -> np.ndarray:
        """Apply discrete updates for the blocks whose sample time is due."""
        new = xd.copy()
        for bid in due:
            plan = self.c.plans[bid]
            if not plan.block.n_dstates:
                continue
            self._values = values
            new[plan.xd_slice] = plan.block.update(
                t, x[plan.x_slice], xd[plan.xd_slice], self._inputs(plan))
        return new

    def inputs_for(self, plan, values) -> list[np.ndarray]:
        self._values = values
        return self._inputs(plan)


# ──────────────────────────────────────────────────────────────
#  Simulate
# ──────────────────────────────────────────────────────────────

def simulate(model: SimModel | CompiledModel,
             t_end: float = 10.0,
             solver: str = "RK45",
             max_step: float | None = None,
             rtol: float = 1e-6,
             atol: float = 1e-9,
             n_points: int = 2000,
             progress=None) -> SimResult:
    """
    Run a model from ``t = 0`` to ``t_end``.

    ``solver`` is one of ``RK45``, ``LSODA``, ``Radau``, ``BDF``, ``DOP853``
    (variable step) or ``ode1``/``ode4`` (fixed step, for comparing against
    hardware that will run a fixed-step controller).
    """
    compiled = model if isinstance(model, CompiledModel) else compile_model(model)
    if t_end <= 0:
        raise SimulationError(f"t_end must be positive, got {t_end}")

    for block in compiled.model:
        block.reset()

    ev = _Evaluator(compiled)
    x, xd = compiled.initial_state()
    run_warnings = list(compiled.warnings)
    if compiled.has_algebraic_loop:
        run_warnings.append(describe_algebraic_loop(compiled))

    # The sample grid: every instant a discrete block must act.
    hits = _sample_hits(compiled.sample_times, t_end)
    t_grid = _output_grid(t_end, n_points, hits)

    times: list[float] = []
    states: list[np.ndarray] = []
    logged: dict[PortRef, list[np.ndarray]] = {}
    delays = [p for p in compiled.plans.values()
              if p.block.type_name == "TransportDelay"]
    stoppers = [p for p in compiled.plans.values()
                if p.block.type_name == "StopSimulation"]
    stopped: list[float] = []

    def record(t: float, x_now: np.ndarray, xd_now: np.ndarray) -> None:
        values = ev.evaluate(t, x_now, xd_now)
        times.append(t)
        states.append(x_now.copy())
        for ref, value in values.items():
            logged.setdefault(ref, []).append(np.atleast_1d(value))
        for plan in delays:
            u = ev.inputs_for(plan, values)
            if u:
                plan.block.record(t, np.atleast_1d(u[0]))
        for plan in stoppers:
            if not stopped and plan.block.should_stop(
                    ev.inputs_for(plan, values)):
                stopped.append(t)

    n_steps = 0
    t_now = 0.0

    # Discrete blocks act at t = 0 as well. Without this first update they
    # hold their initial output through the whole first sample period, and
    # every discrete signal comes out one sample late.
    all_discrete = {bid for bid, p in compiled.plans.items()
                    if p.sample_time > 0 and p.block.n_dstates}
    if all_discrete:
        xd = ev.update_discrete(0.0, x, xd, ev.evaluate(0.0, x, xd),
                                all_discrete)
    record(t_now, x, xd)

    # A StopSimulation block ends the run at the first sample where its input
    # goes non-zero. The check lives in record(), so it sees every logged
    # instant; the loops below stop as soon as it fires.
    spans = _spans(hits, t_end)
    for span_start, span_end in spans:
        if compiled.n_states:
            x, steps = _integrate(ev, compiled, x, xd, span_start, span_end,
                                  solver, max_step, rtol, atol,
                                  t_grid, record, stop_flag=stopped)
            n_steps += steps
        else:
            for t in t_grid[(t_grid > span_start) & (t_grid <= span_end)]:
                record(float(t), x, xd)
                if stopped:
                    break
            n_steps += 1
        if stopped:
            run_warnings.append(
                f"stopped early at t = {stopped[0]:.6g} by a "
                f"StopSimulation block")
            break

        t_now = span_end
        due = _blocks_due(compiled, t_now)
        if due:
            # Log the held value one last time *before* updating, then again
            # after. The two samples at the same instant draw the vertical
            # riser of the staircase; without the first one a zero-order hold
            # is plotted as a ramp between samples.
            record(t_now, x, xd)
            values = ev.evaluate(t_now, x, xd)
            xd = ev.update_discrete(t_now, x, xd, values, due)
            record(t_now, x, xd)
        if progress is not None:
            progress(t_now / t_end)

    result = _assemble(compiled, times, states, logged, run_warnings,
                       solver, n_steps)
    return result


def _sample_hits(sample_times: list[float], t_end: float) -> np.ndarray:
    """Union of every discrete block's sample instants, within the run."""
    if not sample_times:
        return np.zeros(0)
    hits: set[float] = set()
    for ts in sample_times:
        n = int(np.floor(t_end / ts)) + 1
        if n > 2_000_000:
            raise SimulationError(
                f"a sample time of {ts:g} s over {t_end:g} s needs {n:,} "
                f"steps. Raise the sample time or shorten the run."
            )
        hits.update(float(k * ts) for k in range(1, n + 1) if k * ts <= t_end)
    return np.array(sorted(hits))


def _spans(hits: np.ndarray, t_end: float) -> list[tuple[float, float]]:
    """Continuous stretches between consecutive sample hits."""
    edges = [0.0, *[h for h in hits if 0.0 < h <= t_end]]
    if edges[-1] < t_end:
        edges.append(t_end)
    return [(edges[i], edges[i + 1]) for i in range(len(edges) - 1)
            if edges[i + 1] > edges[i]]


def _output_grid(t_end: float, n_points: int, hits: np.ndarray) -> np.ndarray:
    grid = np.linspace(0.0, t_end, max(int(n_points), 2))
    if len(hits):
        grid = np.unique(np.concatenate([grid, hits]))
    return grid


def _blocks_due(compiled: CompiledModel, t: float) -> set[str]:
    due = set()
    for bid, plan in compiled.plans.items():
        ts = plan.sample_time
        if ts <= 0:
            continue
        k = round(t / ts)
        if abs(t - k * ts) <= 1e-9 * max(1.0, t) and k >= 1:
            due.add(bid)
    return due


def _integrate(ev, compiled, x, xd, t0, t1, solver, max_step, rtol, atol,
               t_grid, record, stop_flag=()):
    """Integrate one continuous span, recording on the output grid."""
    inner = t_grid[(t_grid > t0) & (t_grid < t1)]

    def rhs(t, x_vec):
        values = ev.evaluate(t, x_vec, xd)
        return ev.derivatives(t, x_vec, xd, values)

    if solver in FIXED_STEP:
        x_end = _fixed_step(rhs, x, t0, t1, solver, max_step,
                            inner, record, xd)
        return x_end, max(1, len(inner))

    events = _build_events(ev, compiled, xd)
    with _warnings.catch_warnings():
        _warnings.simplefilter("ignore")
        sol = solve_ivp(rhs, (t0, t1), x, method=solver,
                        t_eval=inner if len(inner) else None,
                        events=events or None,
                        max_step=max_step if max_step else np.inf,
                        rtol=rtol, atol=atol, dense_output=False)
    if not sol.success:
        raise SimulationError(
            f"the solver failed between t = {t0:.6g} and {t1:.6g}: "
            f"{sol.message}. Try a stiff method (Radau or BDF), or check for "
            f"a block whose output grows without bound."
        )

    for i, t_i in enumerate(sol.t):
        record(float(t_i), sol.y[:, i], xd)
        if stop_flag:
            break
    return (sol.y[:, -1] if sol.y.shape[1] else x), int(sol.nfev)


def _build_events(ev, compiled, xd):
    """
    One solve_ivp event per zero-crossing signal.

    Landing exactly on a discontinuity matters: integrating through a
    saturation corner makes the local error estimate meaningless, so the step
    controller either shrinks the step towards zero or returns an answer that
    changes with the tolerance.
    """
    probe_t = 0.0
    x0 = np.zeros(compiled.n_states)
    try:
        values = ev.evaluate(probe_t, x0, xd)
        count = len(ev.zero_crossings(probe_t, x0, xd, values))
    except Exception:
        return []
    if not count:
        return []

    def make(i):
        def event(t, x_vec):
            values = ev.evaluate(t, x_vec, xd)
            zc = ev.zero_crossings(t, x_vec, xd, values)
            return float(zc[i]) if i < len(zc) else 1.0
        event.terminal = False
        event.direction = 0
        return event

    return [make(i) for i in range(count)]


def _fixed_step(rhs, x, t0, t1, method, max_step, inner, record, xd):
    """
    Euler (``ode1``) or classical RK4 (``ode4``), stepping exactly onto each
    output point.

    The step grid is built by subdividing each interval *between output times*
    rather than marching a uniform ``h`` and recording whatever state happens
    to be current. Recording the state from the end of the straddling step
    instead introduces an O(h) sampling error that swamps the integrator's own
    accuracy — it made RK4 converge at first order, indistinguishable from
    Euler.
    """
    h_max = max_step if max_step else (t1 - t0)
    edges = [t0, *[float(v) for v in inner if t0 < v < t1], t1]
    t, x_now = t0, x.copy()

    for edge in edges[1:]:
        span = edge - t
        if span <= 0:
            continue
        n = max(int(np.ceil(span / max(h_max, 1e-15))), 1)
        h = span / n
        for _ in range(n):
            if method == "ode1":
                x_now = x_now + h * rhs(t, x_now)
            else:
                k1 = rhs(t, x_now)
                k2 = rhs(t + h / 2, x_now + h / 2 * k1)
                k3 = rhs(t + h / 2, x_now + h / 2 * k2)
                k4 = rhs(t + h, x_now + h * k3)
                x_now = x_now + h / 6 * (k1 + 2 * k2 + 2 * k3 + k4)
            t += h
        t = edge                                # kill accumulated drift
        if edge < t1:
            record(float(edge), x_now, xd)
    return x_now


def _assemble(compiled, times, states, logged, run_warnings, solver, n_steps):
    t = np.asarray(times, dtype=float)
    # Stable sort, and **duplicate timestamps are kept**: two samples at the
    # same instant are how a zero-order hold's step is represented, and the
    # stable order preserves pre-update before post-update.
    order = np.argsort(t, kind="stable")
    t = t[order]

    signals: dict[str, np.ndarray] = {}
    for ref, series in logged.items():
        width = max(len(v) for v in series)
        arr = np.array([np.resize(v, width) for v in series], dtype=float)
        signals[str(ref)] = arr[order]

    state_arr = (np.array(states, dtype=float)[order]
                 if states else np.zeros((0, compiled.n_states)))

    scopes: dict[str, list[str]] = {}
    workspace: dict[str, np.ndarray] = {}
    for bid, plan in compiled.plans.items():
        block = plan.block
        if block.type_name == "Scope":
            sources = []
            for conn in plan.input_conns:
                if conn is not None:
                    sources.append(str(conn.src))
            scopes[block.params.get("title", bid) or bid] = sources
        elif block.type_name == "ToWorkspace":
            conn = plan.input_conns[0] if plan.input_conns else None
            if conn is not None and str(conn.src) in signals:
                workspace[block.params["name"]] = signals[str(conn.src)]

    return SimResult(
        t=t, signals=signals, states=state_arr,
        scopes=scopes, workspace=workspace,
        warnings=run_warnings, solver=solver, n_steps=n_steps,
    )

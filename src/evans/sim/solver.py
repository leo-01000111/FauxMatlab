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
* Each algebraic loop is closed with ``scipy.optimize.fsolve`` on its
  breakers' outputs, loop by loop in signal-flow order.
* Discontinuities are caught by :meth:`~evans.sim.block.Block.zero_crossings`
  events, so a saturation limit or relay switch is hit exactly. The events
  are terminal: integration stops on the crossing, the blocks' **modes** are
  updated, and it restarts. Between crossings the modes stay latched, so the
  right-hand side the solver sees is smooth (see :func:`_integrate`).
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
VARIABLE_STEP = {"RK45", "RK23", "LSODA", "Radau", "BDF", "DOP853"}
FIXED_STEP = {"ode1", "ode2", "ode3", "ode4", "ode5"}

# ── Simulink solver names ──
# People arrive with Simulink's names in their fingers, so those are accepted
# and mapped onto the nearest scipy method. Where the two are not the same
# algorithm the comment says so; the result's ``solver`` field records both
# names, so a run never claims to be something it was not.
SIMULINK_ALIASES = {
    # Dormand–Prince 4(5): the same pair of formulas as ode45.
    "ode45": "RK45",
    # Bogacki–Shampine 2(3): the same pair as ode23.
    "ode23": "RK23",
    # ode113 is a variable-order Adams–Bashforth–Moulton PECE code. DOP853 is
    # a high-order *Runge–Kutta* method, so it is not the equivalent, however
    # well it does at tight tolerances. LSODA is: in its non-stiff mode it
    # runs a variable-order Adams method, and it switches to BDF by itself if
    # the problem turns out to be stiff — a superset of what ode113 does.
    "ode113": "LSODA",
    # Variable-order NDF/BDF; scipy's BDF is the same family (it also uses
    # the NDF modification).
    "ode15s": "BDF",
    # ode23s is a modified Rosenbrock (linearly implicit) method. scipy has no
    # Rosenbrock solver; Radau IIA is a fully implicit Runge–Kutta method of
    # order 5. It shares what matters about ode23s — one-step, L-stable, a
    # Jacobian used every step — so it is the closest, just more accurate and
    # more costly per step.
    "ode23s": "Radau",
    # ode23t is the trapezoidal rule: implicit, one-step, A-stable, for
    # moderately stiff problems. Radau is the implicit one-step method scipy
    # has. It damps very fast oscillations where the trapezoidal rule keeps
    # them, so a lightly damped stiff mode can look more settled than in
    # Simulink — still closer than BDF, a multistep method whose low orders
    # damp harder.
    "ode23t": "Radau",
}

#: Simulink names refused outright, with the reason shown to the user.
UNSUPPORTED = {
    "ode15i": ("ode15i solves fully implicit DAEs, f(t, y, y') = 0, and "
               "Evans models are explicit ODEs (y' = f(t, y)), so there is "
               "nothing for it to do here. Use ode15s for a stiff model."),
}


def solver_choices() -> list[str]:
    """Every name ``simulate`` accepts, Simulink's first."""
    return [*SIMULINK_ALIASES, *sorted(FIXED_STEP), *sorted(VARIABLE_STEP)]


def resolve_solver(name: str) -> tuple[str, bool]:
    """
    Map a solver name onto ``(canonical, is_fixed)``.

    ``canonical`` is the name the integrator dispatches on: a scipy method for
    variable step, ``ode1``–``ode5`` for fixed step. The lookup ignores case,
    because ``ODE45`` and ``rk45`` are obviously meant, and refusing them
    would only teach people to retype.

    An unknown name used to reach ``solve_ivp`` as ``method=…`` and fail with
    scipy's ValueError — or, in a model without continuous states, never
    reach it and run silently. Every name is now checked here, first.
    """
    key = str(name).strip()
    lowered = key.lower()
    if lowered in SIMULINK_ALIASES:
        return SIMULINK_ALIASES[lowered], False
    if lowered in FIXED_STEP:
        return lowered, True
    for variable in VARIABLE_STEP:
        if lowered == variable.lower():
            return variable, False
    if lowered in UNSUPPORTED:
        raise SimulationError(UNSUPPORTED[lowered])
    raise SimulationError(
        f"unknown solver {key!r}. Choose one of: "
        f"{', '.join(solver_choices())}.")


def _solver_label(requested: str, canonical: str) -> str:
    """``"ode45 (RK45)"`` for an alias, just the name otherwise."""
    asked = str(requested).strip().lower()
    if asked in SIMULINK_ALIASES:
        return f"{asked} ({canonical})"
    return canonical


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
        #: Run warnings raised while integrating (chattering zero crossings).
        self.warnings: list[str] = []

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
        """All port values at ``t``, resolving every algebraic loop."""
        if self.c.has_algebraic_loop:
            return self._evaluate_with_loops(t, x, xd)
        return self._sweep(t, x, xd)

    def _sweep(self, t, x, xd) -> dict[PortRef, np.ndarray]:
        self._values = {}
        for bid in self.c.order:
            self._output(bid, t, x, xd)
        return self._values

    def _output(self, bid, t, x, xd, store: bool = True) -> list[np.ndarray]:
        """One block's outputs from the values so far; stored unless told not."""
        plan = self.c.plans[bid]
        block = plan.block
        outs = [np.atleast_1d(np.asarray(v, dtype=float))
                for v in block.output(t, x[plan.x_slice], xd[plan.xd_slice],
                                      self._inputs(plan))]
        if store:
            for port, value in zip(block.outputs, outs):
                self._values[PortRef(bid, port)] = value
        return outs

    # ── algebraic loops ─────────────────────────────────────────

    def _evaluate_with_loops(self, t, x, xd) -> dict[PortRef, np.ndarray]:
        """
        Sweep the model, closing each algebraic loop where the order meets it.

        Loops are solved **one at a time**, in the order the compiler emitted
        them — topological order of the loops and the blocks between them —
        rather than with one ``fsolve`` over every breaker at once. That is
        both cheaper and more robust: ``fsolve`` builds its Jacobian by finite
        differences, one sweep per unknown, so a joint solve pays for every
        loop's unknowns on every loop's sweep, while here each Jacobian is
        only as wide as one loop's breakers and each sweep only re-evaluates
        that loop's own blocks. A loop downstream of another starts from its
        upstream's converged values instead of a half-solved guess, and when
        one fails to converge the error names exactly that loop.
        """
        previous = self._values              # warm start: the last solution
        self._values = {}
        first = {loop.members[0]: loop for loop in self.c.loops}
        order = self.c.order
        at = 0
        while at < len(order):
            loop = first.get(order[at])
            if loop is None:
                self._output(order[at], t, x, xd)
                at += 1
            else:
                self._solve_loop(loop, t, x, xd, previous)
                at += len(loop.members)
        return self._values

    def _solve_loop(self, loop, t, x, xd, previous) -> None:
        """
        Close one loop by solving for its breakers' outputs.

        Guess the breakers' outputs, evaluate the loop's blocks once in their
        compiled order, and compare each breaker's recomputed output with its
        guess. The root of that residual is the consistent solution. Values
        from upstream of the loop are already in place and are not touched.
        """
        refs: list[PortRef] = []
        widths: list[int] = []
        for bid in loop.breakers:
            plan = self.c.plans[bid]
            refs += [PortRef(bid, p) for p in plan.block.outputs]
            widths += plan.output_widths
        guess = np.concatenate([
            previous.get(r, np.zeros(w)) for r, w in zip(refs, widths)])
        breakers = set(loop.breakers)

        def residual(flat: np.ndarray) -> np.ndarray:
            at = 0
            for ref, w in zip(refs, widths):
                self._values[ref] = flat[at:at + w]
                at += w
            recomputed: dict[str, list[np.ndarray]] = {}
            for bid in loop.members:
                # A breaker is evaluated in place but keeps its guess: the
                # blocks after it in the order were promised the guess.
                outs = self._output(bid, t, x, xd, store=bid not in breakers)
                if bid in breakers:
                    recomputed[bid] = outs
            return np.concatenate(
                [v for bid in loop.breakers for v in recomputed[bid]]) - flat

        with _warnings.catch_warnings():
            _warnings.simplefilter("ignore")
            solution, _info, ok, msg = fsolve(residual, guess, full_output=True)
        # Always re-run at the solution: it leaves every member's value
        # consistent with it (fsolve's last call need not have been there).
        error = float(np.max(np.abs(residual(solution)), initial=0.0))
        # Judged by the residual, not by fsolve's flag alone: scipy ≥ 1.15
        # can land on the root of a linear loop (residual ~1e-17, rounding
        # noise) and then report "not making good progress" because the
        # noise cannot be reduced further — a solved loop called a failure.
        scale = 1.0 + float(np.max(np.abs(solution), initial=0.0))
        if ok != 1 and not error <= 1e-9 * scale:
            raise SimulationError(
                f"the algebraic loop through "
                f"{' → '.join(loop.cycle)} did not converge at "
                f"t = {t:.6g} ({msg.strip()}). "
                f"Break it with a UnitDelay or another block without direct "
                f"feedthrough."
            )

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

    # ── zero crossings and modes ────────────────────────────────

    def zero_crossing_layout(self, t, x, xd) -> list[tuple[str, int]]:
        """
        ``(block id, count)`` for every block with zero crossings, in order.

        Counts come from :meth:`~evans.sim.block.Block.n_zero_crossings`. A
        block that does not declare one is asked directly, at the real state
        — and if that raises, the run says so instead of quietly losing every
        event, which is what the old probe at ``x = 0`` did.
        """
        layout: list[tuple[str, int]] = []
        values = None
        for bid, plan in self.c.plans.items():
            n = plan.block.n_zero_crossings(list(plan.input_widths))
            if n is None:
                if values is None:
                    values = self.evaluate(t, x, xd)
                try:
                    n = len(np.atleast_1d(plan.block.zero_crossings(
                        t, x[plan.x_slice], xd[plan.xd_slice],
                        self.inputs_for(plan, values))))
                except Exception as exc:
                    raise SimulationError(
                        f"{bid} ({plan.block.type_name}) failed while "
                        f"counting its zero crossings: {exc}. Declare "
                        f"n_zero_crossings() on the block."
                    ) from exc
            if n:
                layout.append((bid, int(n)))
        return layout

    def zero_crossings(self, t, x, xd, values, layout=None) -> np.ndarray:
        """
        Every zero-crossing value, concatenated in ``layout`` order.

        With a layout, a block returning a different number of values than it
        declared is an error: event ``i`` must mean the same crossing for the
        whole span, or the solver would stop on one and update another.
        """
        if layout is None:
            layout = [(bid, None) for bid in self.c.plans]
        out = []
        for bid, n in layout:
            plan = self.c.plans[bid]
            self._values = values
            zc = np.atleast_1d(np.asarray(plan.block.zero_crossings(
                t, x[plan.x_slice], xd[plan.xd_slice], self._inputs(plan)),
                dtype=float))
            if n is not None and len(zc) != n:
                raise SimulationError(
                    f"{bid} ({plan.block.type_name}) returned {len(zc)} "
                    f"zero-crossing values at t = {t:.6g} but declared {n}")
            if len(zc):
                out.append(zc)
        return np.concatenate(out) if out else np.zeros(0)

    def init_modes(self, t, x, xd) -> None:
        """
        Set every block's modes from scratch at ``(t, x)``, and latch them.

        The model is evaluated *unlatched* first, so each block's mode comes
        from the inputs it really has — not from whatever an earlier run, or
        a default, left latched upstream.
        """
        self.release_modes()
        values = self.evaluate(t, x, xd)
        for plan in self.c.plans.values():
            plan.block.init_modes(t, x[plan.x_slice], xd[plan.xd_slice],
                                  self.inputs_for(plan, values))
        self.update_modes(t, x, xd)

    def update_modes(self, t, x, xd) -> bool:
        """
        Recompute every block's modes at ``(t, x)``, latching them.

        Called at each zero-crossing event, at the start of every continuous
        span (a discrete update may just have pushed an input across a
        threshold), and — by a fixed-step solver — after each major step.

        A mode change upstream changes the inputs downstream, so the pass is
        repeated until nothing moves; chained discontinuities settle in as
        many passes as the chain is long.
        """
        changed_any = False
        for _ in range(len(self.c.plans) + 1):
            values = self.evaluate(t, x, xd)
            changed = False
            for plan in self.c.plans.values():
                if plan.block.update_modes(t, x[plan.x_slice],
                                           xd[plan.xd_slice],
                                           self.inputs_for(plan, values)):
                    changed = True
            if not changed:
                break
            changed_any = True
        return changed_any

    def release_modes(self) -> None:
        """Stop latching: every block evaluates its discontinuity on the spot."""
        for plan in self.c.plans.values():
            plan.block.release_modes()


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

    ``solver`` is one of ``RK45``, ``RK23``, ``LSODA``, ``Radau``, ``BDF``,
    ``DOP853`` (variable step), ``ode1``–``ode5`` (fixed step, for comparing
    against hardware that will run a fixed-step controller), or a Simulink
    name — ``ode45``, ``ode23``, ``ode113``, ``ode15s``, ``ode23s``,
    ``ode23t`` — mapped by :func:`resolve_solver`.
    """
    requested = solver
    solver, _ = resolve_solver(solver)
    solver_label = _solver_label(requested, solver)
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
    ev.init_modes(0.0, x, xd)
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
                ev.update_modes(float(t), x, xd)
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
            ev.update_modes(t_now, x, xd)
            record(t_now, x, xd)
        if progress is not None:
            progress(t_now / t_end)

    run_warnings.extend(ev.warnings)
    ev.release_modes()
    result = _assemble(compiled, times, states, logged, run_warnings,
                       solver_label, n_steps)
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


#: More zero-crossing events than this inside one chatter window and the span
#: stops latching modes (see :func:`_integrate`).
_CHATTER_EVENTS = 50
#: The chatter window, as a fraction of the span (or of ``max_step``).
_CHATTER_WINDOW = 1e-6
#: With zero crossings and no max_step, no step is longer than this fraction
#: of the run (see :func:`_integrate`).
_MIN_STEPS_PER_RUN = 50
#: Stand-in for an exact zero, which counts as positive (see
#: :meth:`~evans.sim.block.Block.zero_crossings`).
_TINY = 1e-300


def _integrate(ev, compiled, x, xd, t0, t1, solver, max_step, rtol, atol,
               t_grid, record, stop_flag=()):
    """
    Integrate one continuous span, recording on the output grid.

    With zero crossings the span is a sequence of smooth pieces. Every event
    is terminal: ``solve_ivp`` stops on the crossing, the state there is
    recorded twice — before and after the modes are updated, so a relay's
    jump is drawn as a vertical edge, like a held sample — and integration
    restarts from the event time with the new modes latched. Between events
    the right-hand side is one smooth function, which is what the step-size
    controller's error estimate assumes; stepping over a kink instead makes
    the answer depend on the tolerance.

    A model that keeps switching without advancing (a relay with no
    hysteresis around a pure integrator, friction at rest under a small
    force) would restart forever. More than ``_CHATTER_EVENTS`` events inside
    a window of ``_CHATTER_WINDOW`` of the span ends latching for the rest
    of the span: the solver then steps on with the modes recomputed after
    every step, and the run carries a warning naming the blocks.
    """
    inner = t_grid[(t_grid > t0) & (t_grid < t1)]

    def rhs(t, x_vec):
        values = ev.evaluate(t, x_vec, xd)
        return ev.derivatives(t, x_vec, xd, values)

    if solver in FIXED_STEP:
        # _fixed_step does not report its steps, so nothing would update a
        # latched mode while it marches: evaluate the discontinuities on the
        # spot instead. Once it takes an ``on_major_step(t, x)`` callback,
        # pass ``lambda t, x: ev.update_modes(t, x, xd)`` and drop this line.
        ev.release_modes()
        x_end = _fixed_step(rhs, x, t0, t1, solver, max_step,
                            inner, record, xd)
        return x_end, max(1, len(inner))

    span = t1 - t0
    h_ref = min(span, max_step) if max_step else span
    window = _CHATTER_WINDOW * h_ref
    # The run's last grid point is t_end itself; nothing else logs it unless a
    # discrete block happens to be due there.
    log_end = t1 >= t_grid[-1] and not _blocks_due(compiled, t1)
    use_grid = len(inner) > 0

    # A discrete update may just have pushed an input across a threshold.
    ev.update_modes(t0, x, xd)
    layout = ev.zero_crossing_layout(t0, x, xd)
    owners = [bid for bid, n in layout for _ in range(n)]
    # Crossings are only looked for at step ends, and with the modes latched
    # a clipped signal is a constant the step controller will happily stride
    # over for the whole span — straight past an input that dips back inside
    # the limits and out again. Without a user max_step, cap the step at a
    # fiftieth of the run, as Simulink does, whenever there is anything to
    # cross.
    step_cap = max_step if max_step else (
        (t_grid[-1] - t_grid[0]) / _MIN_STEPS_PER_RUN if layout else np.inf)
    sides = _sides(ev.zero_crossings(t0, x, xd, ev.evaluate(t0, x, xd),
                                     layout))

    t_s, x_s = t0, np.asarray(x, dtype=float)
    nfev = 0
    recent: list[tuple[float, list[int]]] = []
    while True:
        # t1 rides along in t_eval so the span ends with the state *at* t1,
        # not at the last grid point before it.
        t_eval = (np.append(inner[inner > t_s], t1) if use_grid else None)
        with _warnings.catch_warnings():
            _warnings.simplefilter("ignore")
            sol = solve_ivp(rhs, (t_s, t1), x_s, method=solver,
                            t_eval=t_eval,
                            events=_build_events(ev, layout, xd, t_s, sides)
                            or None,
                            max_step=step_cap,
                            rtol=rtol, atol=atol, dense_output=False)
        nfev += int(sol.nfev)
        if not sol.success:
            raise SimulationError(
                f"the solver failed between t = {t_s:.6g} and {t1:.6g}: "
                f"{sol.message}. Try a stiff method (Radau or BDF), or check "
                f"for a block whose output grows without bound."
            )

        ts, ys = np.asarray(sol.t, dtype=float), np.asarray(sol.y)
        for i in range(len(ts)):
            # The restart point was logged already, and t1 only when it ends
            # the run.
            if ts[i] == t_s or (ts[i] >= t1 and use_grid and not log_end):
                continue
            record(float(ts[i]), ys[:, i], xd)
            if stop_flag:
                return ys[:, i], nfev

        if sol.status != 1:                     # reached t1
            return (ys[:, -1] if len(ts) else x_s), nfev

        # ── a zero crossing ──
        t_e = min(float(te[-1]) for te in sol.t_events if len(te))
        fired = [i for i, te in enumerate(sol.t_events)
                 if len(te) and te[-1] == t_e]
        y_e = np.asarray(sol.y_events[fired[0]][-1], dtype=float)
        if not (len(ts) and ts[-1] == t_e):
            record(t_e, y_e, xd)                # the left limit
            if stop_flag:
                return y_e, nfev
        sides = _cross(ev, layout, rhs, t_e, y_e, xd, fired, sides, h_ref)
        record(t_e, y_e, xd)                    # the right limit
        if stop_flag:
            return y_e, nfev
        t_s, x_s = t_e, y_e

        recent.append((t_e, fired))
        if len(recent) > _CHATTER_EVENTS:
            recent.pop(0)
            if t_e - recent[0][0] <= window:
                blocks = sorted({owners[i] for _, f in recent for i in f})
                ev.warnings.append(
                    f"zero crossings of {', '.join(blocks)} chattered near "
                    f"t = {t_e:.6g} ({_CHATTER_EVENTS} events within "
                    f"{window:.3g} s); their modes were recomputed every "
                    f"solver step instead of latched until t = {t1:.6g}, so "
                    f"the result there depends on the step size")
                x_end, steps = _step_unlatched(
                    ev, rhs, t_s, x_s, t1, xd, solver, max_step, rtol, atol,
                    t_grid, inner if use_grid else None, log_end, record,
                    stop_flag)
                return x_end, nfev + steps
        if t1 - t_s <= 1e-12 * max(1.0, abs(t1)):
            return x_s, nfev


def _sides(zc: np.ndarray) -> np.ndarray:
    """Which side of zero each value is on, an exact zero counting as ``+``."""
    return np.where(np.asarray(zc) >= 0, 1.0, -1.0)


def _cross(ev, layout, rhs, t_e, y_e, xd, fired, sides, h_ref):
    """
    Update the modes at a crossing; return each value's side after it.

    ``solve_ivp`` places the root to within a few ulps, *on either side*. Read
    the modes at ``t_e`` itself and half the time they come out as if the
    crossing had not happened — then the next step finds the same crossing
    again, a hair later, and so on. So the modes are read a little *past* the
    event instead, at ``t_e + ε`` along the old trajectory, with ``ε`` grown
    until the values that fired have really changed sign. Integration still
    restarts from the exact event state; only the decision looks ahead.
    """
    f_old = rhs(t_e, y_e)
    eps = max(1e-10 * h_ref, 1e-13 * abs(t_e))
    for _ in range(5):
        t_n, x_n = t_e + eps, y_e + eps * f_old
        z = _sides(ev.zero_crossings(t_n, x_n, xd,
                                     ev.evaluate(t_n, x_n, xd), layout))
        if all(z[i] != sides[i] for i in fired):
            break
        eps *= 10.0
    ev.update_modes(t_n, x_n, xd)
    return _sides(ev.zero_crossings(t_n, x_n, xd, ev.evaluate(t_n, x_n, xd),
                                    layout))


def _build_events(ev, layout, xd, t_start, sides):
    """
    One terminal ``solve_ivp`` event per zero-crossing value.

    Landing exactly on a discontinuity matters: integrating through a
    saturation corner makes the local error estimate meaningless, so the step
    controller either shrinks the step towards zero or returns an answer that
    changes with the tolerance.

    Each event only fires *away* from the side its value started on
    (``direction = −side``). At ``t_start`` the value is reported as being on
    that side even if it sits a rounding error the other way — that is the
    crossing just handled, and it must not fire again. An exact zero counts
    as positive throughout, so a signal resting on a threshold (friction at
    rest) is quiet until it leaves.

    The model is evaluated once per ``(t, x)``, not once per event: solve_ivp
    calls every event function at the same point in turn.
    """
    if not len(sides):
        return []
    cache: dict = {"key": None, "zc": None}

    def values_at(t, x_vec):
        key = (t, x_vec.tobytes())
        if cache["key"] != key:
            cache["zc"] = ev.zero_crossings(
                t, x_vec, xd, ev.evaluate(t, x_vec, xd), layout)
            cache["key"] = key
        return cache["zc"]

    def make(i):
        side = float(sides[i])

        def event(t, x_vec):
            g = float(values_at(t, x_vec)[i])
            if t == t_start:
                return side * max(abs(g), _TINY)
            return g if g != 0.0 else _TINY
        event.terminal = True
        event.direction = -side
        return event

    return [make(i) for i in range(len(sides))]


def _step_unlatched(ev, rhs, t_s, x_s, t1, xd, solver, max_step, rtol, atol,
                    t_grid, inner, log_end, record, stop_flag):
    """
    Finish a span that chattered: step on, updating the modes after each step.

    Each step still sees one latched mode, so the step-size controller sees a
    smooth function and does not grind towards a zero step on the switching
    surface; the step is capped at the output spacing so the switching is
    resolved at least as finely as it is plotted. Whenever a mode changes the
    stepper is restarted, so no stage carries a derivative from the old mode
    into the new one.
    """
    import scipy.integrate as _ivp

    h_out = (t_grid[-1] - t_grid[0]) / max(len(t_grid) - 1, 1)
    cap = min(max_step, h_out) if max_step else h_out
    pending = list(inner[inner > t_s]) if inner is not None else None
    if pending is not None and log_end:
        pending.append(t1)
    method = getattr(_ivp, solver)

    def fresh(t, y, h):
        return method(rhs, t, y, t1, max_step=cap, rtol=rtol, atol=atol,
                      first_step=min(h, t1 - t) if t1 > t else None)

    stepper, nfev = fresh(t_s, x_s, cap), 0
    while stepper.status == "running":
        t_prev = stepper.t
        message = stepper.step()
        if stepper.status == "failed":
            raise SimulationError(
                f"the solver failed near t = {t_prev:.6g}: {message}. Try a "
                f"stiff method (Radau or BDF).")
        if pending is None:
            record(float(stepper.t), stepper.y, xd)
            if stop_flag:
                break
        elif pending and pending[0] <= stepper.t:
            dense = stepper.dense_output()
            while pending and pending[0] <= stepper.t:
                tp = float(pending.pop(0))
                record(tp, dense(tp), xd)
                if stop_flag:
                    return dense(tp), nfev + stepper.nfev
        if stepper.status == "running" and \
                ev.update_modes(stepper.t, stepper.y, xd):
            nfev += stepper.nfev
            h = stepper.step_size or cap
            stepper = fresh(stepper.t, stepper.y, h)
    return stepper.y, nfev + stepper.nfev


# ── fixed-step methods ──
# Each explicit Runge–Kutta method is its Butcher tableau: nodes ``c``, the
# strictly lower-triangular stage matrix ``A`` (row i is how stage i mixes the
# earlier slopes), and weights ``b``. One loop below runs all of them, so a
# new method is a new table entry, not a new branch.
#
# ode3 and ode5 are the higher-order halves of Simulink's embedded pairs
# (Bogacki–Shampine 3(2), Dormand–Prince 5(4)). Both pairs are FSAL: their
# last stage is the slope at the new point, used only for the error estimate,
# so with a fixed step it is dropped and the weights stop one stage early.
_TABLEAUS: dict[str, tuple[list[float], list[list[float]], list[float]]] = {
    "ode1": ([0.0], [[]], [1.0]),                                   # Euler
    "ode2": ([0.0, 1.0], [[], [1.0]], [1 / 2, 1 / 2]),              # Heun
    "ode3": ([0.0, 1 / 2, 3 / 4],                        # Bogacki–Shampine
             [[], [1 / 2], [0.0, 3 / 4]],
             [2 / 9, 1 / 3, 4 / 9]),
    "ode4": ([0.0, 1 / 2, 1 / 2, 1.0],                        # classical RK4
             [[], [1 / 2], [0.0, 1 / 2], [0.0, 0.0, 1.0]],
             [1 / 6, 1 / 3, 1 / 3, 1 / 6]),
    "ode5": ([0.0, 1 / 5, 3 / 10, 4 / 5, 8 / 9, 1.0],           # Dormand–Prince
             [[],
              [1 / 5],
              [3 / 40, 9 / 40],
              [44 / 45, -56 / 15, 32 / 9],
              [19372 / 6561, -25360 / 2187, 64448 / 6561, -212 / 729],
              [9017 / 3168, -355 / 33, 46732 / 5247, 49 / 176,
               -5103 / 18656]],
             [35 / 384, 0.0, 500 / 1113, 125 / 192, -2187 / 6784, 11 / 84]),
}


def _rk_step(rhs, t, x, h, tableau):
    """One explicit Runge–Kutta step of size ``h`` from ``(t, x)``."""
    c, a, b = tableau
    k: list[np.ndarray] = []
    for ci, row in zip(c, a):
        xi = x
        for aij, kj in zip(row, k):
            if aij:
                xi = xi + (h * aij) * kj
        k.append(rhs(t + ci * h, xi))
    incr = np.zeros_like(x, dtype=float)
    for bi, ki in zip(b, k):
        if bi:
            incr = incr + bi * ki
    return x + h * incr


def _fixed_step(rhs, x, t0, t1, method, max_step, inner, record, xd,
                on_major_step=None):
    """
    A fixed-step explicit Runge–Kutta method — ``ode1`` (Euler) to ``ode5``
    (Dormand–Prince), see ``_TABLEAUS`` — stepping exactly onto each output
    point.

    The step grid is built by subdividing each interval *between output times*
    rather than marching a uniform ``h`` and recording whatever state happens
    to be current. Recording the state from the end of the straddling step
    instead introduces an O(h) sampling error that swamps the integrator's own
    accuracy — it made RK4 converge at first order, indistinguishable from
    Euler.

    ``on_major_step(t, x)``, when given, is called after every completed step
    with the new time and state. It is the hook for work that belongs between
    steps rather than inside one — latching a mode at a zero crossing is what
    it exists for — and on the last substep of an interval it gets the exact
    output instant, not the drifted sum of the substeps.
    """
    tableau = _TABLEAUS[method]
    h_max = max_step if max_step else (t1 - t0)
    edges = [t0, *[float(v) for v in inner if t0 < v < t1], t1]
    t, x_now = t0, x.copy()

    for edge in edges[1:]:
        span = edge - t
        if span <= 0:
            continue
        n = max(int(np.ceil(span / max(h_max, 1e-15))), 1)
        h = span / n
        for i in range(n):
            x_now = _rk_step(rhs, t, x_now, h, tableau)
            t = edge if i == n - 1 else t + h   # kill accumulated drift
            if on_major_step is not None:
                on_major_step(t, x_now)
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

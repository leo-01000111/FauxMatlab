"""
The simulation engine, checked against analytic answers and independent
oracles.

Two oracles are used, chosen so a bug would have to be made twice:

* ``control.step_response`` / ``control.step_response`` on the exact closed-loop
  transfer function, for linear models;
* ``control.interconnect`` + ``input_output_response``, for nonlinear
  continuous models — the one regime where it does apply.
"""

from __future__ import annotations

import control as ctl
import numpy as np
import pytest

from fakematlab.sim.block import BlockError, block_types, create
from fakematlab.sim.blocks import by_category  # noqa: F401  (registers library)
from fakematlab.sim.compile import CompileError, compile_model, describe_algebraic_loop
from fakematlab.sim.model import ModelError, SimModel
from fakematlab.sim.solver import simulate

# ──────────────────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────────────────

def unity_loop(controller=("2, 1", "1, 0"), plant=("1", "1, 1")) -> SimModel:
    """The ch.5 architecture with unity feedback."""
    m = SimModel("ch5")
    m.add("Step", "r", step_time=0.0)
    m.add("Sum", "e", signs="+-")
    m.add("TransferFcn", "K2", num=controller[0], den=controller[1])
    m.add("TransferFcn", "G", num=plant[0], den=plant[1])
    m.connect("r", "e.in1")
    m.connect("e", "K2")
    m.connect("K2", "G")
    m.connect("G", "e.in2")
    return m


def at_times(result, name, times):
    """Sample a logged signal at given instants, taking the held value."""
    trace = result.trace(name)
    idx = np.searchsorted(result.t, np.asarray(times) + 1e-9) - 1
    return trace[np.clip(idx, 0, len(trace) - 1)]


# ──────────────────────────────────────────────────────────────
#  Linear accuracy
# ──────────────────────────────────────────────────────────────

def test_ch5_loop_matches_the_analytic_transfer_function():
    """
    The plan's acceptance test: the course architecture built on the canvas
    must reproduce the analytic ``r → y`` step response to 1e-6.
    """
    model = unity_loop()
    result = simulate(model, t_end=10.0, n_points=2000, rtol=1e-9, atol=1e-12)

    closed = ctl.feedback(ctl.tf([2, 1], [1, 0]) * ctl.tf([1], [1, 1]), 1)
    _, expected = ctl.step_response(closed, T=result.t)

    assert np.max(np.abs(result.trace("G.out") - expected)) < 1e-6


@pytest.mark.parametrize("plant", [
    ("1", "1, 1"), ("4", "1, 1.2, 4"), ("1", "1, 3, 3, 1"), ("1", "1, 1, 0"),
])
def test_open_loop_blocks_match_control(plant):
    m = SimModel("open")
    m.add("Step", "r", step_time=0.0)
    m.add("TransferFcn", "G", num=plant[0], den=plant[1])
    m.connect("r", "G")
    result = simulate(m, t_end=8.0, n_points=800, rtol=1e-10, atol=1e-12)

    _, expected = ctl.step_response(ctl.tf(*[
        [float(c) for c in p.split(",")] for p in plant]), T=result.t)
    assert np.allclose(result.trace("G.out"), expected, atol=1e-6)


def test_solver_converges_as_tolerance_tightens():
    """A result that moves when you tighten the tolerance is not a result."""
    closed = ctl.feedback(ctl.tf([2, 1], [1, 0]) * ctl.tf([1], [1, 1]), 1)
    errors = []
    for rtol in (1e-4, 1e-7, 1e-10):
        r = simulate(unity_loop(), t_end=5.0, n_points=500,
                     rtol=rtol, atol=rtol * 1e-3)
        _, expected = ctl.step_response(closed, T=r.t)
        errors.append(np.max(np.abs(r.trace("G.out") - expected)))
    assert errors[0] > errors[-1]
    assert errors[-1] < 1e-7


@pytest.mark.parametrize("solver", ["RK45", "LSODA", "Radau", "BDF", "ode4"])
def test_every_solver_agrees(solver):
    closed = ctl.feedback(ctl.tf([2, 1], [1, 0]) * ctl.tf([1], [1, 1]), 1)
    kwargs = {"max_step": 0.001} if solver == "ode4" else {}
    r = simulate(unity_loop(), t_end=5.0, n_points=500, solver=solver,
                 rtol=1e-9, atol=1e-12, **kwargs)
    _, expected = ctl.step_response(closed, T=r.t)
    assert np.max(np.abs(r.trace("G.out") - expected)) < 1e-4


# ──────────────────────────────────────────────────────────────
#  Multi-rate — the reason this engine exists
# ──────────────────────────────────────────────────────────────

def test_control_interconnect_cannot_mix_timebases():
    """
    The justification for a hand-written engine, asserted rather than assumed.

    If a future python-control lifts this restriction, this test fails and the
    decision is worth revisiting.
    """
    plant = ctl.tf2ss(ctl.tf([1.0], [1.0, 1.0]))
    p = ctl.ss(plant.A, plant.B, plant.C, plant.D,
               name="plant", inputs="u", outputs="y")
    d = ctl.ss(ctl.c2d(ctl.tf([3.0], [1.0]), 0.02),
               name="ctrl", inputs="e", outputs="u")
    s = ctl.summing_junction(inputs=["r", "-y"], output="e", name="sum")
    with pytest.raises(ValueError, match="timebase"):
        ctl.interconnect([p, d, s], inputs=["r"], outputs=["y"])


def test_discrete_controller_drives_continuous_plant():
    m = SimModel("multirate")
    m.add("Step", "r", step_time=0.0)
    m.add("Sum", "e", signs="+-")
    m.add("DiscretePID", "C", Kp=3.0, Ki=6.0, sample_time=0.02)
    m.add("TransferFcn", "G", num="1", den="1, 1")
    m.connect("r", "e.in1")
    m.connect("e", "C")
    m.connect("C", "G")
    m.connect("G", "e.in2")

    compiled = compile_model(m)
    assert compiled.sample_times == [0.02]
    assert compiled.n_states == 1 and compiled.n_dstates == 3

    result = simulate(m, t_end=3.0, n_points=1500)
    assert result.trace("G.out")[-1] == pytest.approx(1.0, abs=2e-2)


def test_sampled_control_signal_is_piecewise_constant():
    """
    A sampled controller computes at its sample instants and holds.

    An earlier version let the proportional term feed the *live* continuous
    error straight through, so a 50 Hz controller's output changed at every
    solver step — 1498 changes in 3 s instead of 150. The plot looked fine.
    """
    m = SimModel("hold")
    m.add("Step", "r", step_time=0.0)
    m.add("Sum", "e", signs="+-")
    m.add("DiscretePID", "C", Kp=3.0, Ki=6.0, sample_time=0.02)
    m.add("TransferFcn", "G", num="1", den="1, 1")
    m.connect("r", "e.in1")
    m.connect("e", "C")
    m.connect("C", "G")
    m.connect("G", "e.in2")

    u = simulate(m, t_end=3.0, n_points=1500).trace("C.out")
    changes = int(np.sum(np.abs(np.diff(u)) > 1e-12))
    assert changes <= 160, f"{changes} changes — the hold is not holding"
    assert changes >= 140, f"only {changes} changes — samples are being missed"


def test_discrete_transfer_function_matches_control():
    """Sample-for-sample agreement with ``control``'s discrete step response."""
    ts = 0.1
    m = SimModel("dtf")
    m.add("Step", "r", step_time=0.0)
    m.add("DiscreteTF", "H", num="0.5", den="1, -0.5", sample_time=ts)
    m.connect("r", "H")
    result = simulate(m, t_end=1.0, n_points=400)

    grid = np.arange(0.0, 1.0 + 1e-9, ts)
    _, expected = ctl.step_response(
        ctl.TransferFunction([0.5], [1, -0.5], ts), T=grid)
    assert np.allclose(at_times(result, "H.out", grid),
                       np.atleast_1d(expected), atol=1e-12)


def test_two_rates_run_together():
    """A fast inner loop and a slow outer one share one timeline."""
    m = SimModel("two-rate")
    m.add("Step", "r", step_time=0.0)
    m.add("DiscreteTF", "slow", num="1", den="1, 0", sample_time=0.1)
    m.add("DiscreteTF", "fast", num="1", den="1, 0", sample_time=0.025)
    m.connect("r", "slow")
    m.connect("slow", "fast")

    compiled = compile_model(m)
    assert compiled.sample_times == [0.025, 0.1]
    result = simulate(m, t_end=1.0, n_points=400)
    assert np.all(np.isfinite(result.trace("fast.out")))


# ──────────────────────────────────────────────────────────────
#  Nonlinear, against the interconnect oracle
# ──────────────────────────────────────────────────────────────

def test_saturated_loop_matches_interconnect():
    m = SimModel("sat")
    m.add("Step", "r", step_time=0.0)
    m.add("Sum", "e", signs="+-")
    m.add("TransferFcn", "C", num="2, 1", den="1, 0")
    m.add("Saturation", "sat", upper=0.5, lower=-0.5)
    m.add("TransferFcn", "G", num="1", den="1, 1")
    m.connect("r", "e.in1")
    m.connect("e", "C")
    m.connect("C", "sat")
    m.connect("sat", "G")
    m.connect("G", "e.in2")
    ours = simulate(m, t_end=10.0, n_points=1001, rtol=1e-9, atol=1e-12)

    plant = ctl.tf2ss(ctl.tf([1.0], [1.0, 1.0]))
    ctrl = ctl.tf2ss(ctl.tf([2.0, 1.0], [1.0, 0.0]))
    net = ctl.interconnect(
        [ctl.ss(plant.A, plant.B, plant.C, plant.D,
                name="plant", inputs="u", outputs="y"),
         ctl.ss(ctrl.A, ctrl.B, ctrl.C, ctrl.D,
                name="ctrl", inputs="e", outputs="v"),
         ctl.NonlinearIOSystem(None, lambda t, x, u, p: np.clip(u, -0.5, 0.5),
                               inputs="v", outputs="u", name="sat"),
         ctl.summing_junction(inputs=["r", "-y"], output="e", name="sum")],
        inputs=["r"], outputs=["y", "u"])

    grid = np.linspace(0, 10, 1001)
    reference = ctl.input_output_response(net, grid, np.ones_like(grid))
    ours_on_grid = np.interp(grid, ours.t, ours.trace("G.out"))
    assert np.max(np.abs(ours_on_grid - reference.outputs[0])) < 1e-3


def test_saturation_actually_clips():
    m = SimModel("clip")
    m.add("Step", "r", step_time=0.0, final=10.0)
    m.add("Saturation", "sat", upper=2.0, lower=-2.0)
    m.connect("r", "sat")
    result = simulate(m, t_end=1.0, n_points=100)
    assert result.trace("sat.out").max() == pytest.approx(2.0)


def test_integrator_anti_windup_beats_plain_integration():
    """
    Anti-windup must actually reduce overshoot.

    With a saturating actuator, an unclamped integrator keeps charging while
    the output sits at the limit, and has to discharge again before the loop
    can recover — the classic large overshoot.

    The setpoint has to be *reachable*: with a DC gain of 2 and a ±1 actuator,
    ``y = 1`` needs only ``u = 0.5`` in steady state, while the transient
    still drives the controller into saturation. A setpoint beyond what the
    actuator can hold would leave both variants pinned at the limit with no
    overshoot to compare.
    """
    def run(limit: bool) -> np.ndarray:
        m = SimModel("windup")
        m.add("Step", "r", step_time=0.0, final=1.0)
        m.add("Sum", "e", signs="+-")
        m.add("PID", "C", Kp=2.0, Ki=5.0, limit=limit, upper=1.0, lower=-1.0)
        m.add("Saturation", "sat", upper=1.0, lower=-1.0)
        m.add("TransferFcn", "G", num="2", den="1, 1")
        m.connect("r", "e.in1")
        m.connect("e", "C")
        m.connect("C", "sat")
        m.connect("sat", "G")
        m.connect("G", "e.in2")
        return simulate(m, t_end=20.0, n_points=2000).trace("G.out")

    with_aw, without = run(limit=True), run(limit=False)
    assert without.max() > 1.15, "the run did not wind up, so it proves nothing"
    assert with_aw.max() < 1.10
    assert with_aw.max() < without.max()
    # Both must still reach the setpoint.
    assert with_aw[-1] == pytest.approx(1.0, abs=1e-2)
    assert without[-1] == pytest.approx(1.0, abs=1e-2)


def test_relay_feedback_oscillates():
    """A relay in a feedback loop must produce a sustained limit cycle."""
    m = SimModel("relay")
    m.add("Constant", "r", value=0.0)
    m.add("Sum", "e", signs="+-")
    m.add("Relay", "R", on_point=0.01, off_point=-0.01,
          on_value=1.0, off_value=-1.0)
    m.add("TransferFcn", "G", num="1", den="1, 3, 3, 1")
    m.connect("r", "e.in1")
    m.connect("e", "R")
    m.connect("R", "G")
    m.connect("G", "e.in2")

    y = simulate(m, t_end=40.0, n_points=4000).trace("G.out")
    tail = y[len(y) // 2:]
    assert np.ptp(tail) > 0.05, "the relay loop settled instead of oscillating"
    assert np.all(np.abs(tail) < 10.0), "the relay loop diverged"


# ──────────────────────────────────────────────────────────────
#  Algebraic loops
# ──────────────────────────────────────────────────────────────

def test_algebraic_loop_is_detected_and_solved():
    m = SimModel("alg")
    m.add("Step", "r", step_time=0.0)
    m.add("Sum", "s", signs="+-")
    m.add("Gain", "k", gain=0.5)
    m.connect("r", "s.in1")
    m.connect("s", "k")
    m.connect("k", "s.in2")

    compiled = compile_model(m)
    assert compiled.has_algebraic_loop
    assert set(compiled.algebraic_loop) == {"s", "k"}

    message = describe_algebraic_loop(compiled)
    assert "Algebraic loop" in message
    assert "UnitDelay" in message

    # y = r − 0.5·y  ⇒  y = 1/1.5
    result = simulate(m, t_end=1.0, n_points=20)
    assert result.trace("s.out")[-1] == pytest.approx(1 / 1.5, rel=1e-8)


def test_a_state_block_breaks_the_loop():
    """An integrator or strictly proper TF has no feedthrough, so no loop."""
    assert not compile_model(unity_loop()).has_algebraic_loop


def test_unit_delay_breaks_an_algebraic_loop():
    m = SimModel("broken")
    m.add("Step", "r", step_time=0.0)
    m.add("Sum", "s", signs="+-")
    m.add("Gain", "k", gain=0.5)
    m.add("UnitDelay", "z", sample_time=0.05)
    m.connect("r", "s.in1")
    m.connect("s", "k")
    m.connect("k", "z")
    m.connect("z", "s.in2")
    assert not compile_model(m).has_algebraic_loop


def test_biproper_transfer_function_creates_a_loop():
    """``(s+2)/(s+1)`` has D ≠ 0, so it does feed through."""
    m = SimModel("biproper")
    m.add("Step", "r", step_time=0.0)
    m.add("Sum", "s", signs="+-")
    m.add("TransferFcn", "G", num="1, 2", den="1, 1")
    m.connect("r", "s.in1")
    m.connect("s", "G")
    m.connect("G", "s.in2")
    assert compile_model(m).has_algebraic_loop


# ──────────────────────────────────────────────────────────────
#  Structure, errors and persistence
# ──────────────────────────────────────────────────────────────

def test_an_input_port_takes_one_wire():
    m = unity_loop()
    with pytest.raises(ModelError, match="already has a wire"):
        m.connect("K2", "e.in1")


def test_unknown_port_is_named_helpfully():
    m = unity_loop()
    with pytest.raises(ModelError, match="no input port"):
        m.connect("r", "e.nope")


def test_ambiguous_port_must_be_named():
    m = unity_loop()
    m.add("Sum", "s2", signs="++")
    with pytest.raises(ModelError, match="name one explicitly"):
        m.connect("r", "s2")


def test_improper_transfer_function_is_refused():
    with pytest.raises(BlockError, match="improper"):
        create("TransferFcn", "bad", num="1, 1", den="1")


def test_unknown_parameter_is_refused():
    with pytest.raises(BlockError, match="no parameter"):
        create("Gain", "g", gian=2.0)


def test_empty_model_is_refused():
    with pytest.raises(CompileError, match="empty"):
        compile_model(SimModel("nothing"))


def test_unconnected_input_warns_but_runs():
    m = SimModel("loose")
    m.add("Gain", "k", gain=2.0)
    m.add("Terminator", "t")
    m.connect("k", "t")
    result = simulate(m, t_end=1.0, n_points=10)
    assert any("unconnected" in w for w in result.warnings)


def test_model_round_trips_through_json(tmp_path):
    original = unity_loop()
    original.move("G", 120.0, 40.0)
    path = tmp_path / "loop.fmdl"
    original.save(path)
    restored = SimModel.load(path)

    assert set(restored.blocks) == set(original.blocks)
    assert len(restored.connections) == len(original.connections)
    assert restored.placement("G").x == 120.0

    a = simulate(original, t_end=5.0, n_points=300)
    b = simulate(restored, t_end=5.0, n_points=300)
    assert np.allclose(a.trace("G.out"), b.trace("G.out"))


def test_loading_a_newer_model_is_refused():
    data = unity_loop().to_dict()
    data["version"] = 99
    with pytest.raises(ModelError, match="newer version"):
        SimModel.from_dict(data)


def test_scopes_and_workspace_are_collected():
    m = unity_loop()
    m.add("Scope", "view", n_inputs=2, title="Loop")
    m.add("ToWorkspace", "log", name="y_out")
    m.connect("G", "view.in1")
    m.connect("K2", "view.in2")
    m.connect("G", "log")

    result = simulate(m, t_end=2.0, n_points=200)
    assert result.scopes["Loop"] == ["G.out", "K2.out"]
    assert "y_out" in result.workspace
    assert result.workspace["y_out"].shape[0] == len(result.t)


def test_every_registered_block_can_be_instantiated():
    """The palette must not offer a block that cannot be created."""
    for name in block_types():
        block = create(name, f"{name}_1")
        assert block.type_name == name
        assert isinstance(block.label(), str)


# ──────────────────────────────────────────────────────────────
#  Linearisation — the bridge to the analysis tabs
# ──────────────────────────────────────────────────────────────

def test_linearisation_recovers_an_open_loop_transfer_function():
    from fakematlab.sim.linearize import linearize

    m = SimModel("open")
    m.add("Constant", "r", value=0.0)
    m.add("TransferFcn", "G", num="2", den="1, 3, 2")
    m.connect("r", "G")

    got = linearize(m, "G", "G").transfer_function()
    assert np.allclose(np.sort(ctl.poles(got).real), [-2.0, -1.0], atol=1e-5)
    assert float(ctl.dcgain(got)) == pytest.approx(1.0, rel=1e-5)


def test_linearised_canvas_loop_equals_the_exact_algebra():
    """
    The bridge, end to end: a loop drawn on the canvas must linearise to the
    same transfer function :mod:`fakematlab.core.algebra` derives symbolically
    for the equivalent block diagram.
    """
    from fakematlab.sim.linearize import linearize

    m = unity_loop()
    m.remove("r")
    m.add("Constant", "r", value=0.0)
    m.connect("r", "e.in1")

    got = linearize(m, "e.in1", "G").transfer_function()
    exact = ctl.feedback(ctl.tf([2, 1], [1, 0]) * ctl.tf([1], [1, 1]), 1)

    assert np.allclose(np.sort(ctl.poles(got)), np.sort(ctl.poles(exact)),
                       atol=1e-5)
    assert float(ctl.dcgain(got)) == pytest.approx(float(ctl.dcgain(exact)),
                                                   rel=1e-5)


@pytest.mark.parametrize("u0", [0.5, 1.0, 2.0])
def test_linearisation_depends_on_the_operating_point(u0):
    """
    For ``y' = −y + u²`` the linear DC gain is ``2u₀``.

    A nonlinearity linearises differently at different operating points; that
    is the whole reason to linearise numerically rather than read coefficients
    off the blocks.
    """
    from fakematlab.sim.linearize import linearize

    m = SimModel("nonlinear")
    m.add("Constant", "r", value=u0)
    m.add("MathFunction", "sq", function="square")
    m.add("TransferFcn", "G", num="1", den="1, 1")
    m.connect("r", "sq")
    m.connect("sq", "G")

    dc = float(ctl.dcgain(linearize(m, "sq", "G").ss))
    assert dc == pytest.approx(2 * u0, rel=1e-4)


def test_linearisation_inside_saturation_keeps_the_loop_gain():
    from fakematlab.sim.linearize import linearize, steady_state

    m = SimModel("sat-lin")
    m.add("Constant", "r", value=0.0)
    m.add("Sum", "e", signs="+-")
    m.add("Gain", "K", gain=4.0)
    m.add("Saturation", "sat", upper=1.0, lower=-1.0)
    m.add("TransferFcn", "G", num="1", den="1, 1")
    m.connect("r", "e.in1")
    m.connect("e", "K")
    m.connect("K", "sat")
    m.connect("sat", "G")
    m.connect("G", "e.in2")

    got = linearize(m, "e.in1", "G", operating_point=steady_state(m))
    # Inside the limits the saturation is a unit gain, so this is 4/(s+5).
    assert np.allclose(ctl.poles(got.ss).real, [-5.0], atol=1e-4)


def test_linearisation_refuses_an_algebraic_loop():
    from fakematlab.sim.linearize import LinearizationError, linearize

    m = SimModel("alg")
    m.add("Step", "r", step_time=0.0)
    m.add("Sum", "s", signs="+-")
    m.add("Gain", "k", gain=0.5)
    m.connect("r", "s.in1")
    m.connect("s", "k")
    m.connect("k", "s.in2")

    with pytest.raises(LinearizationError, match="algebraic loop"):
        linearize(m, "s.in1", "s")


def test_linearisation_reports_an_unnamed_port_clearly():
    from fakematlab.sim.linearize import LinearizationError, linearize

    m = unity_loop()
    with pytest.raises(LinearizationError, match="name one"):
        linearize(m, "e", "G")


def test_steady_state_refuses_a_model_that_never_settles():
    from fakematlab.sim.linearize import LinearizationError, steady_state

    m = SimModel("ramp")
    m.add("Step", "r", step_time=0.0)
    m.add("Integrator", "i")
    m.connect("r", "i")
    with pytest.raises(LinearizationError, match="not settled"):
        steady_state(m, t_settle=5.0)


# ──────────────────────────────────────────────────────────────
#  Subsystems
# ──────────────────────────────────────────────────────────────

def pi_subsystem_model(num: str = "2, 1") -> SimModel:
    """The unity loop with its controller wrapped in a subsystem."""
    inner = SimModel("PI")
    inner.add("Inport", "e_in", port_name="e", order=1)
    inner.add("TransferFcn", "pi", num=num, den="1, 0")
    inner.add("Outport", "u_out", port_name="u", order=1)
    inner.connect("e_in", "pi")
    inner.connect("pi", "u_out")

    m = SimModel("outer")
    m.add("Step", "r", step_time=0.0)
    m.add("Sum", "e", signs="+-")
    m.add("Subsystem", "C", name="PI").set_inner(inner)
    m.add("TransferFcn", "G", num="1", den="1, 1")
    m.connect("r", "e.in1")
    m.connect("e", "C.e")
    m.connect("C.u", "G")
    m.connect("G", "e.in2")
    return m


def test_subsystem_ports_come_from_its_inports_and_outports():
    model = pi_subsystem_model()
    sub = model.block("C")
    assert sub.inputs == ["e"]
    assert sub.outputs == ["u"]


def test_flattening_splices_the_contents_in():
    from fakematlab.sim.compile import flatten

    flat = flatten(pi_subsystem_model())
    assert set(flat.blocks) == {"r", "e", "G", "C/pi"}
    wires = {str(c) for c in flat.connections}
    assert "e.out → C/pi.in" in wires
    assert "C/pi.out → G.in" in wires
    # No trace of the boundary is left for the engine to worry about.
    assert not any(b.type_name in ("Subsystem", "Inport", "Outport")
                   for b in flat)


def test_a_subsystem_simulates_identically_to_the_flat_model():
    grouped = simulate(pi_subsystem_model(), t_end=10.0, n_points=800,
                       rtol=1e-9, atol=1e-12)
    flat = simulate(unity_loop(), t_end=10.0, n_points=800,
                    rtol=1e-9, atol=1e-12)
    assert np.allclose(grouped.trace("G.out"), flat.trace("G.out"), atol=1e-7)


def test_a_loop_through_a_subsystem_is_still_detected():
    """
    Flattening is what makes this work: a recursive evaluator would treat the
    subsystem as one opaque block and miss the cycle inside it.
    """
    inner = SimModel("gain")
    inner.add("Inport", "i", port_name="in", order=1)
    inner.add("Gain", "k", gain=0.5)
    inner.add("Outport", "o", port_name="out", order=1)
    inner.connect("i", "k")
    inner.connect("k", "o")

    m = SimModel("loop through subsystem")
    m.add("Step", "r", step_time=0.0)
    m.add("Sum", "s", signs="+-")
    m.add("Subsystem", "S", name="gain").set_inner(inner)
    m.connect("r", "s.in1")
    m.connect("s", "S.in")
    m.connect("S.out", "s.in2")

    compiled = compile_model(m)
    assert compiled.has_algebraic_loop
    assert "S/k" in compiled.algebraic_loop
    # And it is still solved correctly: y = r − 0.5y.
    assert simulate(m, t_end=1.0, n_points=20).trace("s.out")[-1] == \
        pytest.approx(1 / 1.5, rel=1e-8)


def test_nested_subsystems_flatten_all_the_way_down():
    from fakematlab.sim.compile import flatten

    deepest = SimModel("deepest")
    deepest.add("Inport", "i", port_name="in", order=1)
    deepest.add("Gain", "g", gain=3.0)
    deepest.add("Outport", "o", port_name="out", order=1)
    deepest.connect("i", "g")
    deepest.connect("g", "o")

    middle = SimModel("middle")
    middle.add("Inport", "i", port_name="in", order=1)
    middle.add("Subsystem", "inner", name="deepest").set_inner(deepest)
    middle.add("Outport", "o", port_name="out", order=1)
    middle.connect("i", "inner.in")
    middle.connect("inner.out", "o")

    top = SimModel("top")
    top.add("Constant", "c", value=2.0)
    top.add("Subsystem", "mid", name="middle").set_inner(middle)
    top.add("TransferFcn", "G", num="1", den="1, 1")
    top.connect("c", "mid.in")
    top.connect("mid.out", "G")

    flat = flatten(top)
    assert "mid/inner/g" in flat.blocks
    result = simulate(top, t_end=10.0, n_points=200)
    assert result.trace("G.out")[-1] == pytest.approx(6.0, rel=1e-3)


def test_stray_boundary_ports_are_refused():
    m = SimModel("stray")
    m.add("Step", "r", step_time=0.0)
    m.add("Outport", "o", port_name="out", order=1)
    m.connect("r", "o")
    with pytest.raises(CompileError, match="boundary of a subsystem"):
        compile_model(m)


def test_a_subsystem_round_trips_through_json(tmp_path):
    path = tmp_path / "nested.fmdl"
    pi_subsystem_model().save(path)
    restored = SimModel.load(path)
    assert restored.block("C").inputs == ["e"]
    assert np.allclose(
        simulate(restored, t_end=5.0, n_points=200).trace("G.out"),
        simulate(pi_subsystem_model(), t_end=5.0, n_points=200).trace("G.out"))


# ──────────────────────────────────────────────────────────────
#  Blocks added to complete the library
# ──────────────────────────────────────────────────────────────

def test_zero_pole_block_matches_the_equivalent_transfer_function():
    m = SimModel("zpk")
    m.add("Step", "r", step_time=0.0)
    m.add("ZeroPole", "H", zeros="-2", poles="-1, -3", gain=6.0)
    m.connect("r", "H")
    result = simulate(m, t_end=8.0, n_points=500, rtol=1e-10, atol=1e-12)

    expected_tf = ctl.tf([6.0, 12.0], [1.0, 4.0, 3.0])
    _, expected = ctl.step_response(expected_tf, T=result.t)
    assert np.allclose(result.trace("H.out"), expected, atol=1e-6)


def test_zero_pole_refuses_more_zeros_than_poles():
    with pytest.raises(BlockError, match="improper"):
        create("ZeroPole", "bad", zeros="-1, -2", poles="-3")


def test_stop_simulation_ends_the_run_early():
    m = SimModel("stop")
    m.add("Step", "r", step_time=2.0)
    m.add("StopSimulation", "halt")
    m.connect("r", "halt")
    result = simulate(m, t_end=10.0, n_points=500)
    assert result.t[-1] < 4.0
    assert any("stopped early" in w for w in result.warnings)


def test_prbs_is_binary_and_repeatable():
    m = SimModel("prbs")
    m.add("PRBS", "u", amplitude=2.0, sample_time=0.1, seed=7)
    m.add("Terminator", "t")
    m.connect("u", "t")
    first = simulate(m, t_end=3.0, n_points=300).trace("u.out")
    second = simulate(m, t_end=3.0, n_points=300).trace("u.out")

    assert set(np.unique(np.round(first, 9))) <= {-2.0, 2.0}
    assert np.allclose(first, second), "the same seed must give the same run"


def test_backlash_holds_while_the_slack_is_taken_up():
    m = SimModel("backlash")
    m.add("Ramp", "r", slope=1.0)
    m.add("Backlash", "b", width=0.4, x0=0.0)
    m.connect("r", "b")
    result = simulate(m, t_end=3.0, n_points=600)
    y = result.trace("b.out")
    t = result.t

    # Inside the first half-width of travel the output must not move.
    assert np.max(np.abs(y[t < 0.15])) < 1e-2
    # Once engaged it tracks the input, lagging by the half-width.
    late = t > 2.0
    assert np.allclose(y[late], t[late] - 0.2, atol=0.05)

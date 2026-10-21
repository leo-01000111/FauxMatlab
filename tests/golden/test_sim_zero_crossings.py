"""
Zero crossings with latched modes, checked against analytic switching times.

Each model here is built so the instant of every discontinuity is known in
closed form — a ramp reaching a limit, a sine reaching a relay threshold — so
"the solver stopped on the crossing" can be checked to a few ulps rather
than eyeballed off a plot.
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from evans.sim import block as block_mod
from evans.sim.blocks import by_category  # noqa: F401  (registers library)
from evans.sim.blocks.nonlinear import Saturation
from evans.sim.compile import compile_model
from evans.sim.model import SimModel
from evans.sim.solver import SimulationError, _Evaluator, simulate

# ──────────────────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────────────────


def ramp_into_saturation(x0: float = 0.0, slope: float = 1.0,
                         upper: float = 0.7) -> SimModel:
    """An integrated constant (a ramp *state*) into a limit, then integrated."""
    m = SimModel("corner")
    m.add("Constant", "k", value=slope)
    m.add("Integrator", "ramp", x0=x0)
    m.add("Saturation", "sat", upper=upper, lower=-10.0)
    m.add("Integrator", "y")
    m.connect("k", "ramp")
    m.connect("ramp", "sat")
    m.connect("sat", "y")
    return m


def relay_loop() -> SimModel:
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
    return m


def nearest(result, t_star: float) -> float:
    return float(np.min(np.abs(result.t - t_star)))


# ──────────────────────────────────────────────────────────────
#  Locating crossings
# ──────────────────────────────────────────────────────────────

def test_saturation_corner_is_located_exactly():
    """
    The ramp ``x = t`` reaches the 0.7 limit at exactly ``t = 0.7``; the
    run must log a sample there, and the integral of the clipped ramp must
    then be exact — ``0.7²/2 + 0.7·(2 − 0.7)`` — because every piece the
    solver integrated was a polynomial it integrates without error.
    """
    result = simulate(ramp_into_saturation(), t_end=2.0, n_points=201)
    assert nearest(result, 0.7) < 1e-12
    assert result.t[-1] == pytest.approx(2.0)
    assert result.trace("y.out")[-1] == pytest.approx(
        0.7 ** 2 / 2 + 0.7 * 1.3, abs=1e-12)
    # On the limit the output is the limit, not the input.
    late = result.t > 0.7 + 1e-9
    assert np.all(result.trace("sat.out")[late] == 0.7)


def test_crossing_time_follows_the_initial_state():
    """
    The state, not a probe at ``x = 0``, decides where the crossing is:
    starting the ramp at 0.2 moves the corner to ``t = 0.5``.
    """
    result = simulate(ramp_into_saturation(x0=0.2), t_end=1.0, n_points=101)
    assert nearest(result, 0.5) < 1e-12
    assert result.trace("y.out")[-1] == pytest.approx(
        (0.2 * 0.5 + 0.5 ** 2 / 2) + 0.7 * 0.5, abs=1e-12)


def test_event_count_does_not_depend_on_the_initial_state():
    compiled = compile_model(ramp_into_saturation())
    ev = _Evaluator(compiled)
    x0, xd0 = compiled.initial_state()
    counts = {len(ev.zero_crossings(0.0, x, xd0,
                                    ev.evaluate(0.0, x, xd0),
                                    ev.zero_crossing_layout(0.0, x, xd0)))
              for x in (x0, x0 + 5.0, x0 - 50.0)}
    assert counts == {2}


class _FragileSaturation(Saturation):
    """A Saturation whose crossing function cannot be evaluated at u = 0."""
    type_name = "_TestFragileSaturation"

    def zero_crossings(self, t, x, xd, u):
        if np.any(np.atleast_1d(u[0]) == 0.0):
            raise ZeroDivisionError("undefined at zero")
        return super().zero_crossings(t, x, xd, u)


class _UndeclaredBrokenCrossing(Saturation):
    """No declared count, and a crossing function that always raises."""
    type_name = "_TestUndeclaredBrokenCrossing"

    def n_zero_crossings(self, input_widths):
        return None

    def zero_crossings(self, t, x, xd, u):
        raise ValueError("broken")


@pytest.fixture
def test_blocks(monkeypatch):
    for cls in (_FragileSaturation, _UndeclaredBrokenCrossing):
        monkeypatch.setitem(block_mod._REGISTRY, cls.type_name, cls)


def test_a_block_that_cannot_be_probed_at_zero_keeps_its_events(test_blocks):
    """
    The old count probe evaluated every block at ``x = 0``, swallowed the
    exception this block raises there, and ran with no events at all.
    """
    m = SimModel("fragile")
    m.add("Constant", "k", value=-1.0)
    m.add("Integrator", "ramp", x0=2.0)
    m.add("_TestFragileSaturation", "sat", upper=1.5, lower=-10.0)
    m.add("Integrator", "y")
    m.connect("k", "ramp")
    m.connect("ramp", "sat")
    m.connect("sat", "y")
    result = simulate(m, t_end=1.0, n_points=101)
    assert nearest(result, 0.5) < 1e-12
    # 1.5 held for 0.5 s, then the falling ramp from 1.5 to 1.0.
    assert result.trace("y.out")[-1] == pytest.approx(0.75 + 0.625, abs=1e-12)


def test_a_failing_crossing_count_is_reported_not_swallowed(test_blocks):
    m = SimModel("broken")
    m.add("Constant", "k", value=1.0)
    m.add("Integrator", "i")
    m.add("_TestUndeclaredBrokenCrossing", "sat")
    m.connect("k", "i")
    m.connect("i", "sat")
    with pytest.raises(SimulationError, match="counting its zero crossings"):
        simulate(m, t_end=1.0)


# ──────────────────────────────────────────────────────────────
#  Modes
# ──────────────────────────────────────────────────────────────

def test_relay_switches_at_its_hysteresis_thresholds():
    """
    ``sin t`` into a relay with points ±0.5: on at ``π/6`` (rising through
    +0.5), off at ``7π/6`` (falling through −0.5), on again at ``13π/6``.
    Without memory the relay would switch off already at ``5π/6``.
    """
    m = SimModel("hyst")
    m.add("Sine", "s")
    m.add("Relay", "R", on_point=0.5, off_point=-0.5,
          on_value=1.0, off_value=-1.0)
    m.add("Integrator", "I")
    m.connect("s", "R")
    m.connect("R", "I")
    result = simulate(m, t_end=8.0, n_points=161)
    t, r = result.t, result.trace("R.out")

    edges = t[1:][np.diff(r) != 0]
    assert np.allclose(edges, [np.pi / 6, 7 * np.pi / 6, 13 * np.pi / 6],
                       atol=1e-9)
    # A jump is logged twice at the same instant: left limit, right limit.
    k = int(np.argmin(np.abs(t - np.pi / 6)))
    assert np.sum(np.abs(t - t[k]) < 1e-15) == 2

    # ∫ relay: −π/6 + (7π/6 − π/6) − (13π/6 − 7π/6) + (8 − 13π/6)
    expected = -np.pi / 6 + np.pi - np.pi + (8 - 13 * np.pi / 6)
    assert result.trace("I.out")[-1] == pytest.approx(expected, abs=1e-8)


@pytest.mark.parametrize("condition", [">=", ">"])
def test_switch_changes_input_exactly_at_the_threshold(condition):
    """Pass −1 until a ramp state reaches 1.3, then 2: ∫ = −1.3 + 2·1.7."""
    m = SimModel("switch")
    m.add("Constant", "one", value=1.0)
    m.add("Integrator", "c")
    m.add("Constant", "a", value=2.0)
    m.add("Constant", "b", value=-1.0)
    m.add("Switch", "sw", threshold=1.3, condition=condition)
    m.add("Integrator", "y")
    m.connect("one", "c")
    m.connect("a", "sw.in1")
    m.connect("c", "sw.control")
    m.connect("b", "sw.in3")
    m.connect("sw", "y")
    result = simulate(m, t_end=3.0, n_points=31)

    assert nearest(result, 1.3) < 1e-12
    assert result.trace("y.out")[-1] == pytest.approx(-1.3 + 2 * 1.7, abs=1e-11)
    sw = result.trace("sw.out")
    assert np.all(sw[result.t < 1.3 - 1e-9] == -1.0)
    assert np.all(sw[result.t > 1.3 + 1e-9] == 2.0)


def test_relay_loop_is_insensitive_to_the_tolerance():
    """
    The relay limit cycle at ``rtol = 1e-3`` must agree with a tight run.
    Stepping over the switches made the loose run wrong by ~0.06 (and,
    with the relay's memory never updated, wrong in kind as well).
    """
    ref = simulate(relay_loop(), t_end=10.0, n_points=1001,
                   rtol=1e-10, atol=1e-12)
    loose = simulate(relay_loop(), t_end=10.0, n_points=1001,
                     rtol=1e-3, atol=1e-9)
    on_ref = np.interp(ref.t, loose.t, loose.trace("G.out"))
    assert np.max(np.abs(on_ref - ref.trace("G.out"))) < 1e-3


def test_saturation_is_insensitive_to_the_tolerance():
    """A sine clipped at ±0.5 and integrated: loose and tight runs agree."""
    def run(rtol):
        m = SimModel("sat-sine")
        m.add("Sine", "s", frequency=3.0)
        m.add("Saturation", "sat", upper=0.5, lower=-0.5)
        m.add("Integrator", "I")
        m.connect("s", "sat")
        m.connect("sat", "I")
        return simulate(m, t_end=10.0, n_points=501, rtol=rtol, atol=1e-12)

    loose, tight = run(1e-3), run(1e-10)
    # Every corner found at both tolerances (a latched, clipped constant
    # once let the loose run stride straight past whole excursions) ...
    assert len(loose.t) == len(tight.t)
    # ... so the two agree to far better than the loose tolerance.
    assert np.max(np.abs(loose.trace("I.out") - tight.trace("I.out"))) < 1e-5


def test_friction_at_rest_stays_at_rest_without_events():
    """With no force, ``v ≡ 0`` sits exactly on the crossing — and is quiet."""
    m = SimModel("rest")
    m.add("Constant", "F", value=0.0)
    m.add("Sum", "s", signs="+-")
    m.add("CoulombFriction", "fr", offset=0.1, gain=1.0)
    m.add("Integrator", "v")
    m.connect("F", "s.in1")
    m.connect("s", "v")
    m.connect("v", "fr")
    m.connect("fr", "s.in2")
    result = simulate(m, t_end=5.0, n_points=51)
    assert np.all(result.trace("v.out") == 0.0)
    assert not result.warnings


def test_linearisation_on_the_limit_has_zero_gain():
    from evans.sim.linearize import OperatingPoint, linearize

    m = SimModel("sat-lin")
    m.add("Integrator", "I", x0=3.0)
    m.add("Saturation", "sat", upper=1.0, lower=-1.0)
    m.add("TransferFcn", "G", num="1", den="1, 1")
    m.connect("I", "sat")
    m.connect("sat", "G")
    compiled = compile_model(m)
    x0, xd0 = compiled.initial_state()
    outside = linearize(m, "sat.in", "G",
                        operating_point=OperatingPoint(0.0, x0, xd0))
    assert np.allclose(outside.ss.B, 0.0)
    x_in = x0.copy()
    x_in[compiled.plans["I"].x_slice] = 0.2
    inside = linearize(m, "sat.in", "G",
                       operating_point=OperatingPoint(0.0, x_in, xd0))
    assert float(np.abs(inside.ss.B).sum()) > 0.5


# ──────────────────────────────────────────────────────────────
#  Chattering
# ──────────────────────────────────────────────────────────────

def _chattering_relay() -> SimModel:
    """A relay without hysteresis around a pure integrator: x' = −sign x."""
    m = SimModel("chatter")
    m.add("Constant", "r", value=0.0)
    m.add("Sum", "e", signs="+-")
    m.add("Relay", "R", on_point=0.0, off_point=0.0)
    m.add("Integrator", "I", x0=0.5)
    m.connect("r", "e.in1")
    m.connect("e", "R")
    m.connect("R", "I")
    m.connect("I", "e.in2")
    return m


def _stuck_friction() -> SimModel:
    """A force below the Coulomb level on a mass at rest."""
    m = SimModel("stuck")
    m.add("Constant", "F", value=0.05)
    m.add("Sum", "s", signs="+-")
    m.add("CoulombFriction", "fr", offset=0.1, gain=1.0)
    m.add("Integrator", "v")
    m.connect("F", "s.in1")
    m.connect("s", "v")
    m.connect("v", "fr")
    m.connect("fr", "s.in2")
    return m


@pytest.mark.parametrize("build, block, signal, t_switch", [
    (_chattering_relay, "R", "I.out", 0.5),
    (_stuck_friction, "fr", "v.out", 0.0),
])
def test_chattering_finishes_with_a_warning(build, block, signal, t_switch):
    started = time.perf_counter()
    result = simulate(build(), t_end=5.0, n_points=501)
    assert time.perf_counter() - started < 10.0, "chattering hung the run"

    assert result.t[-1] == pytest.approx(5.0)
    assert any("chattered" in w and block in w for w in result.warnings)
    # It stays on the switching surface, within the output spacing.
    tail = result.trace(signal)[result.t > t_switch + 0.1]
    assert np.max(np.abs(tail)) < 0.02

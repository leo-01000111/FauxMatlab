"""
Models with more than one algebraic loop, checked against closed forms.

A single loop can be closed by guessing any one signal in it. Two loops —
side by side, chained, or sharing a block — need every cycle cut, and each
solved with the right upstream values in place. Every case here is linear, so
the consistent solution is known exactly.
"""

from __future__ import annotations

import numpy as np
import pytest

from evans.sim.blocks import by_category  # noqa: F401  (registers library)
from evans.sim.compile import compile_model, describe_algebraic_loop
from evans.sim.model import SimModel
from evans.sim.solver import simulate

# ──────────────────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────────────────

def add_feedback_loop(m: SimModel, name: str, source: str,
                      k: float, h: float) -> None:
    """``source → name_s(+-) → name_k (K) → name_h (H) → name_s.in2``."""
    m.add("Sum", f"{name}_s", signs="+-")
    m.add("Gain", f"{name}_k", gain=k)
    m.add("Gain", f"{name}_h", gain=h)
    m.connect(source, f"{name}_s.in1")
    m.connect(f"{name}_s", f"{name}_k")
    m.connect(f"{name}_k", f"{name}_h")
    m.connect(f"{name}_h", f"{name}_s.in2")


def closed(u: float, k: float, h: float) -> float:
    """The forward-path output of a negative feedback loop: u·K/(1+K·H)."""
    return u * k / (1 + k * h)


def two_independent_loops() -> SimModel:
    m = SimModel("two loops")
    m.add("Step", "ra", step_time=0.0)
    m.add("Constant", "rb", value=3.0)
    add_feedback_loop(m, "a", "ra", k=2.0, h=0.5)
    add_feedback_loop(m, "b", "rb", k=4.0, h=0.25)
    return m


def final(result, name: str) -> float:
    return float(result.trace(name)[-1])


# ──────────────────────────────────────────────────────────────
#  Structure
# ──────────────────────────────────────────────────────────────

def test_two_independent_loops_are_both_found():
    compiled = compile_model(two_independent_loops())
    assert len(compiled.loops) == 2
    assert [set(c) for c in compiled.algebraic_loops] == [
        {"a_s", "a_k", "a_h"}, {"b_s", "b_k", "b_h"}]
    # One breaker per loop: a single cycle needs only one signal guessed.
    assert [len(loop.breakers) for loop in compiled.loops] == [1, 1]
    assert len(compiled.loop_breakers) == 2
    # The old single-loop view still points at the first one.
    assert compiled.algebraic_loop == compiled.loops[0].cycle


def test_each_loops_members_are_contiguous_in_the_order():
    compiled = compile_model(two_independent_loops())
    for loop in compiled.loops:
        start = compiled.order.index(loop.members[0])
        assert compiled.order[start:start + len(loop.members)] == loop.members


def test_a_reported_cycle_follows_the_wires():
    compiled = compile_model(two_independent_loops())
    cycle = compiled.loops[0].cycle
    assert cycle[0] == cycle[-1]
    wires = {(c.src.block, c.dst.block) for c in compiled.model.connections}
    assert all((a, b) in wires for a, b in zip(cycle, cycle[1:]))


def test_the_message_names_every_loop():
    compiled = compile_model(two_independent_loops())
    message = describe_algebraic_loop(compiled)
    assert "2 algebraic loops" in message
    for cycle in compiled.algebraic_loops:
        assert " → ".join(cycle) in message
    assert "UnitDelay" in message


def test_linearisation_still_refuses_and_names_both_loops():
    from evans.sim.linearize import LinearizationError, linearize

    with pytest.raises(LinearizationError, match="algebraic loop") as info:
        linearize(two_independent_loops(), "a_s.in1", "a_k")
    assert "a_s" in str(info.value) and "b_s" in str(info.value)


# ──────────────────────────────────────────────────────────────
#  Solutions
# ──────────────────────────────────────────────────────────────

def test_two_independent_loops_each_match_their_closed_form():
    result = simulate(two_independent_loops(), t_end=1.0, n_points=20)
    assert final(result, "a_k") == pytest.approx(closed(1.0, 2.0, 0.5),
                                                  rel=1e-8)
    assert final(result, "b_k") == pytest.approx(closed(3.0, 4.0, 0.25),
                                                  rel=1e-8)


def test_two_cycles_sharing_a_sum_are_one_loop_with_one_breaker():
    """``s = r − a·s − b·s``: both cycles pass through ``s``, so it cuts both."""
    m = SimModel("shared sum")
    m.add("Step", "r", step_time=0.0)
    m.add("Sum", "s", signs="+--")
    m.add("Gain", "ga", gain=0.5)
    m.add("Gain", "gb", gain=1.5)
    m.connect("r", "s.in1")
    m.connect("s", "ga")
    m.connect("ga", "s.in2")
    m.connect("s", "gb")
    m.connect("gb", "s.in3")

    compiled = compile_model(m)
    assert len(compiled.loops) == 1
    assert compiled.loop_breakers == ["s"]
    assert set(compiled.loops[0].members) == {"s", "ga", "gb"}
    # The message names one cycle and the block only the other one uses.
    assert "coupled" in describe_algebraic_loop(compiled)

    result = simulate(m, t_end=1.0, n_points=20)
    assert final(result, "s") == pytest.approx(1 / (1 + 0.5 + 1.5), rel=1e-8)


def test_two_coupled_cycles_through_different_sums():
    """
    ``s1 = r − c2·s2`` and ``s2 = c1·s1 − c3·s2``: a big cycle through both
    sums and a small one round ``s2``, so s2 = c1·r / (1 + c3 + c1·c2).
    """
    c1, c2, c3 = 2.0, 0.5, 1.0
    m = SimModel("coupled")
    m.add("Step", "r", step_time=0.0)
    m.add("Sum", "s1", signs="+-")
    m.add("Sum", "s2", signs="+-")
    m.add("Gain", "g1", gain=c1)
    m.add("Gain", "g2", gain=c2)
    m.add("Gain", "g3", gain=c3)
    m.connect("r", "s1.in1")
    m.connect("s1", "g1")
    m.connect("g1", "s2.in1")
    m.connect("s2", "g2")
    m.connect("g2", "s1.in2")
    m.connect("s2", "g3")
    m.connect("g3", "s2.in2")

    compiled = compile_model(m)
    assert len(compiled.loops) == 1
    assert compiled.loop_breakers == ["s2"]   # on both cycles

    result = simulate(m, t_end=1.0, n_points=20)
    s2 = c1 / (1 + c3 + c1 * c2)
    assert final(result, "s2") == pytest.approx(s2, rel=1e-8)
    assert final(result, "s1") == pytest.approx(1 - c2 * s2, rel=1e-8)


def test_a_block_feeding_itself_is_a_loop():
    """A self-loop is a one-block component, and still an algebraic loop."""
    m = SimModel("self")
    m.add("Step", "r", step_time=0.0)
    m.add("Sum", "s", signs="+-")
    m.connect("r", "s.in1")
    m.connect("s", "s.in2")

    compiled = compile_model(m)
    assert compiled.algebraic_loop == ["s", "s"]
    assert compiled.loop_breakers == ["s"]
    assert final(simulate(m, t_end=1.0, n_points=20), "s") == \
        pytest.approx(0.5, rel=1e-8)


def test_a_loop_inside_a_subsystem_feeding_one_outside():
    """
    The inner loop is upstream of the outer one, so it must be solved first:
    the outer loop then sees its converged output, not a guess.
    """
    inner = SimModel("inner loop")
    inner.add("Inport", "i", port_name="in", order=1)
    inner.add("Outport", "o", port_name="out", order=1)
    add_feedback_loop(inner, "L", "i", k=3.0, h=1.0)
    inner.connect("L_k", "o")

    m = SimModel("two levels")
    m.add("Step", "r", step_time=0.0)
    m.add("Subsystem", "S", name="inner loop").set_inner(inner)
    m.connect("r", "S.in")
    add_feedback_loop(m, "outer", "S.out", k=1.0, h=2.0)

    compiled = compile_model(m)
    assert len(compiled.loops) == 2
    assert "S/L_s" in compiled.loops[0].cycle        # upstream comes first
    assert "outer_s" in compiled.loops[1].cycle

    result = simulate(m, t_end=1.0, n_points=20)
    inner_y = closed(1.0, 3.0, 1.0)
    assert final(result, "S/L_k") == pytest.approx(inner_y, rel=1e-8)
    assert final(result, "outer_k") == pytest.approx(
        closed(inner_y, 1.0, 2.0), rel=1e-8)


def test_a_loop_and_a_unit_delay_elsewhere():
    m = two_independent_loops()
    m.add("UnitDelay", "z", sample_time=0.1)
    m.connect("a_k", "z")

    compiled = compile_model(m)
    assert len(compiled.loops) == 2            # the delay is not in a loop
    result = simulate(m, t_end=1.0, n_points=50)
    assert final(result, "a_k") == pytest.approx(1.0, rel=1e-8)
    assert final(result, "b_k") == pytest.approx(6.0, rel=1e-8)
    # The delay holds the loop's (constant) output from one sample before.
    assert final(result, "z") == pytest.approx(1.0, rel=1e-8)


def test_a_loop_is_solved_on_every_step_of_a_continuous_run():
    """A loop around a feedthrough block, driven by a moving input."""
    m = SimModel("moving")
    m.add("Sine", "u", amplitude=1.0, frequency=1.0)
    add_feedback_loop(m, "a", "u", k=2.0, h=0.5)
    m.add("Ramp", "v", slope=1.0)
    add_feedback_loop(m, "b", "v", k=1.0, h=3.0)

    result = simulate(m, t_end=2.0, n_points=40)
    u = result.trace("u")
    v = result.trace("v")
    assert np.allclose(result.trace("a_k"), closed(1.0, 2.0, 0.5) * u,
                       atol=1e-9)
    assert np.allclose(result.trace("b_k"), closed(1.0, 1.0, 3.0) * v,
                       atol=1e-9)

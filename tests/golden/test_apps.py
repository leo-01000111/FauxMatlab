"""
The apps' arithmetic: collections, snapshots, the viewer, the designer, the
PID tuner.

All of it headless. An app whose numbers can only be checked by looking at a
window is an app whose numbers do not get checked, which is how v1 shipped six
wrong transfer functions behind a green test suite.
"""

from __future__ import annotations

import control as ctl
import numpy as np
import pytest

from fakematlab.core.architecture import CourseArchitecture
from fakematlab.core.collection import (
    MAX_SNAPSHOTS,
    Snapshot,
    SnapshotStore,
    SystemCollection,
    restore_snapshot,
    take_snapshot,
)
from fakematlab.core.designer import (
    Compensator,
    closed_loop_poles,
    damping_of,
    evaluate,
    gain_for_damping,
    gain_for_overshoot,
    point_to_gain,
)
from fakematlab.core.freqresp import bode
from fakematlab.core.pidtune import (
    NEUTRAL_PHASE,
    PIDKind,
    crossover_for,
    default_crossover,
    phase_margin_for,
    tune,
    tune_by_sliders,
)
from fakematlab.core.viewer import (
    CHARACTERISTICS,
    Characteristic,
    ResponseKind,
    compute,
)

#: 1/(s+1)³ — one gain crossover, a finite gain margin, and the analytic
#: answers are known: GM = 8 at ω = √3.
THIRD_ORDER = ctl.tf([1], [1, 3, 3, 1])
#: The ch.8 root-locus workhorse, 1/(s(s+1)(s+2)).
LOCUS_PLANT = ctl.tf([1], [1, 3, 2, 0])


# ──────────────────────────────────────────────────────────────
#  Collections
# ──────────────────────────────────────────────────────────────

def test_duplicate_names_are_kept_apart_not_replaced():
    """
    Two systems added under one name are two systems.

    Replacing would silently discard the curve the user wanted to compare
    against — the exact opposite of what a viewer is for.
    """
    collection = SystemCollection()
    collection.add("design", ctl.tf([1], [1, 1]))
    collection.add("design", ctl.tf([2], [1, 2]))
    assert collection.names == ["design", "design (2)"]
    assert len(collection) == 2


def test_colours_survive_hiding_a_curve():
    collection = SystemCollection()
    for name in ("a", "b", "c"):
        collection.add(name, ctl.tf([1], [1, 1]))
    before = [e.colour for e in collection]
    collection.set_visible("b", False)
    assert [e.colour for e in collection] == before
    assert [e.name for e in collection.visible] == ["a", "c"]


def test_state_space_entries_convert_on_demand():
    sys = ctl.ss([[0, 1], [-2, -3]], [[0], [1]], [[1, 0]], [[0]])
    entry = SystemCollection().add("ss", sys)
    assert isinstance(entry.tf, ctl.TransferFunction)
    assert np.allclose(np.sort(np.atleast_1d(ctl.poles(entry.tf)).real),
                       [-2.0, -1.0])


# ──────────────────────────────────────────────────────────────
#  Snapshots
# ──────────────────────────────────────────────────────────────

def test_a_snapshot_does_not_follow_later_edits():
    """
    The whole point: a snapshot is of the past.

    Storing transfer-function *objects* would make this pass or fail depending
    on whether ``set_block`` happens to rebind or mutate — so coefficients are
    stored instead, and this test pins that down.
    """
    arch = CourseArchitecture(G=ctl.tf([1], [1, 1]))
    snapshot = take_snapshot(arch, "before")
    arch.set_block("G", ctl.tf([99], [1, 7]))
    assert np.allclose(np.atleast_1d(snapshot.tf("G").num[0][0]), [1.0])
    assert np.allclose(np.atleast_1d(snapshot.tf("G").den[0][0]), [1.0, 1.0])


def test_restore_puts_every_block_back():
    arch = CourseArchitecture(G=ctl.tf([1], [1, 1]), K2=ctl.tf([3], [1]))
    snapshot = take_snapshot(arch, "design 1")
    arch.set_block("G", ctl.tf([5], [1, 5]))
    arch.set_block("K2", ctl.tf([1, 1], [1, 0]))

    restore_snapshot(arch, snapshot)
    assert np.allclose(np.atleast_1d(arch.block_tf("K2").num[0][0]), [3.0])
    assert np.allclose(np.atleast_1d(arch.block_tf("G").den[0][0]), [1.0, 1.0])


def test_a_malformed_snapshot_leaves_the_architecture_alone():
    arch = CourseArchitecture(G=ctl.tf([1], [1, 1]))
    broken = Snapshot(label="broken", blocks={"nonsense": ((1.0,), (1.0,))})
    with pytest.raises(ValueError, match="no usable blocks"):
        restore_snapshot(arch, broken)
    assert np.allclose(np.atleast_1d(arch.block_tf("G").den[0][0]), [1.0, 1.0])


def test_the_snapshot_store_is_bounded_and_labels_stay_unique():
    arch = CourseArchitecture()
    store = SnapshotStore()
    for _ in range(MAX_SNAPSHOTS + 4):
        store.take(arch, "design")
    assert len(store) == MAX_SNAPSHOTS
    assert len(set(store.labels)) == MAX_SNAPSHOTS


def test_the_store_becomes_a_collection_of_closed_loops():
    arch = CourseArchitecture(G=ctl.tf([1], [1, 1]))
    store = SnapshotStore()
    store.take(arch, "P = 1")
    arch.set_block("K2", ctl.tf([4], [1]))
    store.take(arch, "P = 4")

    collection = store.collection()
    assert collection.names == ["P = 1", "P = 4"]
    # T = KG/(1+KG) → DC gain K/(1+K): 0.5 and 0.8.
    gains = [float(ctl.dcgain(entry.tf)) for entry in collection]
    assert gains == pytest.approx([0.5, 0.8], rel=1e-9)


def test_a_snapshot_survives_a_round_trip_through_json():
    arch = CourseArchitecture(G=ctl.tf([2], [1, 0.5]))
    original = take_snapshot(arch, "saved", note="ch.8 exercise")
    restored = Snapshot.from_dict(original.as_dict())
    assert restored == original


# ──────────────────────────────────────────────────────────────
#  The LTI Viewer's data
# ──────────────────────────────────────────────────────────────

@pytest.fixture
def pair() -> SystemCollection:
    collection = SystemCollection()
    collection.add("second order", ctl.tf([4], [1, 1.2, 4]))
    collection.add("first order", ctl.tf([1], [1, 1]))
    return collection


@pytest.mark.parametrize("kind", list(ResponseKind))
def test_every_response_kind_produces_curves(pair, kind):
    data = compute(pair, kind, set(CHARACTERISTICS[kind]))
    assert data.curves, f"{kind.value} produced nothing"
    assert all(len(c.x) == len(c.y) for c in data.curves)


def test_only_bode_asks_for_two_panels(pair):
    assert compute(pair, ResponseKind.BODE).panels == ("main", "phase")
    assert compute(pair, ResponseKind.STEP).panels == ("main",)


def test_frequencies_are_raw_not_log(pair):
    """
    The renderer applies the log transform; this module must not.

    Emitting ``log10(ω)`` here and letting pyqtgraph take the log again is the
    bug that silently deleted everything below ω = 1 from every v1 Bode plot,
    so it gets a test rather than a comment.
    """
    data = compute(pair, ResponseKind.BODE)
    assert data.log_x
    for curve in data.curves:
        assert curve.x.min() > 0, "a raw ω axis cannot contain zero"
        assert curve.x.max() / curve.x.min() > 100, \
            "these look like log values, not frequencies"


def test_a_characteristic_that_does_not_apply_is_dropped(pair):
    """Asking for a rise time on a Nyquist plot adds nothing, and raises nothing."""
    data = compute(pair, ResponseKind.NYQUIST, {Characteristic.RISE})
    assert data.marks == []


def test_step_characteristics_match_the_metrics_module(pair):
    from fakematlab.core.timeresp import compute_step_metrics, step_response

    data = compute(pair, ResponseKind.STEP, {Characteristic.PEAK})
    peak = next(m for m in data.marks if m.name == "second order")
    reference = compute_step_metrics(
        step_response(ctl.tf([4], [1, 1.2, 4])))
    assert peak.x == pytest.approx(reference.tp, rel=1e-6)
    assert peak.y == pytest.approx(reference.y_max, rel=1e-6)
    # ζ = 0.3 → Mp ≈ 37%.
    assert "37" in peak.label or "36" in peak.label


def test_bode_margins_match_the_analytic_values():
    """1/(s+1)³ has GM = 8 (18.06 dB) at ω = √3 — the ch.6 worked example."""
    collection = SystemCollection()
    collection.add("L", THIRD_ORDER)
    data = compute(collection, ResponseKind.BODE, {Characteristic.MARGINS})
    gm_mark = next(m for m in data.marks if "GM" in m.label)
    assert gm_mark.x == pytest.approx(np.sqrt(3.0), rel=1e-3)
    assert float(gm_mark.label.split("=")[1].split()[0]) == \
        pytest.approx(20 * np.log10(8.0), abs=0.05)


def test_every_system_shares_one_time_axis(pair):
    """
    A fast system and a slow one must be drawn over the same span, or the
    comparison the viewer exists to make cannot be made.
    """
    data = compute(pair, ResponseKind.STEP)
    spans = {float(c.x[-1]) for c in data.curves}
    assert len(spans) == 1


def test_hiding_a_system_removes_its_curve(pair):
    pair.set_visible("first order", False)
    data = compute(pair, ResponseKind.STEP)
    assert [c.name for c in data.curves] == ["second order"]


# ──────────────────────────────────────────────────────────────
#  The designer
# ──────────────────────────────────────────────────────────────

def test_a_point_on_the_locus_recovers_its_own_gain():
    """
    Round trip: take a known gain, find where its pole is, ask which gain puts
    a pole there, and get the gain back.
    """
    K_known = 1.5
    pole = max(closed_loop_poles(LOCUS_PLANT, K_known),
               key=lambda p: p.imag)
    result = point_to_gain(LOCUS_PLANT, pole)
    assert result.K == pytest.approx(K_known, rel=1e-3)
    assert result.distance < 1e-3
    assert result.on_locus


def test_a_point_off_the_locus_is_projected_onto_it():
    """
    The magnitude condition ``K = 1/|L(s)|`` is only meaningful *on* the
    locus. Off it, the nearest achievable pole is the honest answer, and the
    reported distance says how far off the request was.
    """
    request = complex(-0.5, 3.0)            # well away from the branches
    result = point_to_gain(LOCUS_PLANT, request)
    assert result.distance > 0.1
    assert not result.on_locus
    # Whatever gain came back, its poles really are the ones reported.
    assert np.allclose(np.sort_complex(closed_loop_poles(LOCUS_PLANT,
                                                         result.K)),
                       np.sort_complex(result.poles))


def test_gain_for_damping_hits_the_textbook_answer():
    """
    The ch.8 exercise, worked by hand.

    For ``1/(s(s+1)(s+2))`` the characteristic polynomial is
    ``s³ + 3s² + 2s + K``. Demanding ζ = 0.5 puts the dominant pair at
    ``ωn(−½ ± j√3/2)``; matching coefficients gives ``ωn + a = 3`` and
    ``ωn(ωn + a) = 2``, so ``ωn = 2/3``, the third pole is at −7/3, and

        s³ + 3s² + 2s + 28/27 = (s² + ⅔s + 4/9)(s + 7/3)

    — an exact **K = 28/27**, which is what the tolerance here is tight
    enough to distinguish from a nearby wrong answer.
    """
    result = gain_for_damping(LOCUS_PLANT, 0.5)
    assert result is not None
    assert result.zeta == pytest.approx(0.5, abs=1e-4)
    assert result.pole.real == pytest.approx(-1 / 3, rel=1e-4)
    assert abs(result.pole.imag) == pytest.approx(np.sqrt(3) / 3, rel=1e-4)
    assert result.K == pytest.approx(28 / 27, rel=1e-5)


def test_overshoot_and_damping_targets_agree():
    """16.3% overshoot is ζ = 0.5, so the two entry points must coincide."""
    by_zeta = gain_for_damping(LOCUS_PLANT, 0.5)
    by_overshoot = gain_for_overshoot(LOCUS_PLANT, 16.303)
    assert by_overshoot is not None
    assert by_overshoot.K == pytest.approx(by_zeta.K, rel=1e-4)


def test_an_unreachable_damping_returns_none_rather_than_a_wrong_gain():
    """
    ``1/(s+1)`` has one real branch that never leaves the real axis, so no
    gain gives ζ = 0.5. That is an answer, not a failure.
    """
    assert gain_for_damping(ctl.tf([1], [1, 1]), 0.5) is None


def test_damping_of_a_real_pole_is_one():
    zeta, wn = damping_of(complex(-3.0, 0.0))
    assert zeta == pytest.approx(1.0)
    assert wn == pytest.approx(3.0)


def test_the_locus_does_not_move_when_only_the_gain_does():
    """
    The gesture depends on it: the curve is fixed and the gain is a position
    along it, so the locus is computed for the unit-gain compensator.
    """
    plant = LOCUS_PLANT
    quiet = evaluate(plant, Compensator(gain=1.0))
    loud = evaluate(plant, Compensator(gain=25.0))
    assert np.allclose(quiet.locus.roots, loud.locus.roots, equal_nan=True)
    # ...while the closed-loop poles certainly do move.
    assert not np.allclose(np.sort_complex(quiet.closed_loop_poles),
                           np.sort_complex(loud.closed_loop_poles))


def test_evaluate_reports_instability_instead_of_metrics():
    summary = evaluate(LOCUS_PLANT, Compensator(gain=50.0))
    assert not summary.stable
    assert summary.metrics is None
    assert "right half plane" in summary.note


def test_a_compensator_needs_conjugate_pairs():
    assert Compensator(zeros=[-1 + 2j, -1 - 2j]).is_real_coefficient()
    assert not Compensator(poles=[-1 + 2j]).is_real_coefficient()


def test_a_lead_section_bends_the_locus_left():
    """
    The reason to add one: with a lead, damping targets that the bare plant
    cannot reach become reachable.
    """
    bare = gain_for_damping(LOCUS_PLANT, 0.85)
    lead = Compensator(gain=1.0, zeros=[-1.0], poles=[-10.0])
    with_lead = gain_for_damping(
        lead.tf() * LOCUS_PLANT, 0.85)
    assert with_lead is not None
    if bare is not None:
        assert with_lead.wn > bare.wn


# ──────────────────────────────────────────────────────────────
#  The PID tuner
# ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind,wc,pm", [
    (PIDKind.PI, 0.5, 60.0),
    (PIDKind.PI, 0.3, 45.0),
    (PIDKind.PID, 0.5, 60.0),
    (PIDKind.PID, 1.2, 50.0),
    (PIDKind.PID, 0.9, 75.0),
    (PIDKind.PD, 1.2, 50.0),
])
def test_the_tuner_hits_the_target_exactly(kind, wc, pm):
    """
    The whole design is two equations in two unknowns, solved in closed form,
    so the achieved crossover and margin are not approximations — they are the
    ones that were asked for.
    """
    result = tune(THIRD_ORDER, kind, wc=wc, pm_deg=pm)
    assert result.feasible, result.note
    assert result.achieved_wc == pytest.approx(wc, rel=1e-4)
    assert result.achieved_pm_deg == pytest.approx(pm, rel=1e-4)


def test_the_achieved_margin_agrees_with_an_independent_bode():
    """Checked against the margin routine the tabs use, not against itself."""
    result = tune(THIRD_ORDER, PIDKind.PID, wc=0.8, pm_deg=55.0)
    independent = bode(result.C * THIRD_ORDER)
    assert independent.pm_deg == pytest.approx(55.0, rel=1e-4)
    assert independent.wc == pytest.approx(0.8, rel=1e-4)


def test_a_pi_cannot_add_phase_and_says_so():
    """
    ``1/(s+1)³`` at ω = 1.2 needs +20.6° from the controller. A PI has only
    ``Kp − j·Ki/ω``, which is never above the real axis, so the honest answer
    is a refusal that names the reason.
    """
    result = tune(THIRD_ORDER, PIDKind.PI, wc=1.2, pm_deg=50.0)
    assert not result.feasible
    assert result.params.Kp == 0.0
    assert "only ever *subtracts* phase" in result.note
    assert "PID" in result.note                 # and what to do instead


def test_a_pd_cannot_subtract_phase_and_says_so():
    result = tune(THIRD_ORDER, PIDKind.PD, wc=0.5, pm_deg=60.0)
    assert not result.feasible
    assert "only ever *adds* phase" in result.note


def test_a_pid_covers_both_signs():
    for wc in (0.5, 1.2):
        assert tune(THIRD_ORDER, PIDKind.PID, wc=wc, pm_deg=55.0).feasible


def test_p_honours_the_crossover_and_reports_the_margin_it_got():
    """
    One free parameter cannot meet two targets. The crossover is met; the
    margin is measured and explained rather than claimed.
    """
    result = tune(THIRD_ORDER, PIDKind.P, wc=0.5, pm_deg=60.0)
    assert result.feasible
    assert result.achieved_wc == pytest.approx(0.5, rel=1e-4)
    assert result.achieved_pm_deg != pytest.approx(60.0, rel=1e-3)
    assert "one free parameter" in result.note


def test_the_default_pi_crossover_leaves_real_integral_action():
    """
    Defining the neutral crossover as "where the controller needs no phase"
    is right for a PID and wrong for a PI: at that frequency the integral and
    proportional terms cancel and ``Ki`` comes out at ~1e-6, a P controller
    wearing a PI's name. The PI therefore aims below it.
    """
    assert NEUTRAL_PHASE["PI"] < 0
    result = tune_by_sliders(THIRD_ORDER, PIDKind.PI)
    assert result.feasible
    assert result.params.Ki > 0.05 * result.params.Kp


def test_the_transient_slider_maps_to_phase_margin():
    assert phase_margin_for(0.0) == pytest.approx(45.0)
    assert phase_margin_for(0.5) == pytest.approx(60.0)
    assert phase_margin_for(1.0) == pytest.approx(75.0)
    # Out-of-range positions are clamped, not extrapolated into nonsense.
    assert phase_margin_for(-3.0) == pytest.approx(45.0)


def test_the_response_time_slider_spans_four_decades():
    slow = crossover_for(THIRD_ORDER, -1.0, 60.0, PIDKind.PID)
    fast = crossover_for(THIRD_ORDER, +1.0, 60.0, PIDKind.PID)
    assert fast / slow == pytest.approx(1e4, rel=1e-6)


def test_a_faster_target_really_is_faster():
    """The slider has to do what its label says."""
    slow = tune_by_sliders(THIRD_ORDER, PIDKind.PID, speed=-0.25)
    fast = tune_by_sliders(THIRD_ORDER, PIDKind.PID, speed=+0.25)
    assert fast.achieved_wc > slow.achieved_wc
    assert fast.metrics.tr_1090 < slow.metrics.tr_1090


def test_a_more_robust_target_overshoots_less():
    aggressive = tune_by_sliders(THIRD_ORDER, PIDKind.PID, transient=0.0)
    robust = tune_by_sliders(THIRD_ORDER, PIDKind.PID, transient=1.0)
    assert robust.metrics.Mp_pct < aggressive.metrics.Mp_pct


def test_the_default_crossover_is_where_the_plant_has_the_needed_phase():
    from fakematlab.core.freqresp import response

    wc = default_crossover(THIRD_ORDER, 60.0)
    _, phase = response(THIRD_ORDER, np.array([wc]))
    assert float(np.degrees(phase[0])) == pytest.approx(-120.0, abs=0.5)


def test_a_double_integrator_falls_back_rather_than_failing():
    """∠G = −180° at every ω, so there is no phase crossing to find."""
    wc = default_crossover(ctl.tf([1], [1, 0, 0]), 60.0)
    assert np.isfinite(wc) and wc > 0


def test_a_pi_on_a_type_one_plant_is_flagged():
    result = tune_by_sliders(ctl.tf([1], [1, 1, 0]), PIDKind.PI)
    assert result.feasible
    assert "already contains an integrator" in result.note


# ──────────────────────────────────────────────────────────────
#  The console's app commands
# ──────────────────────────────────────────────────────────────

@pytest.fixture
def app_sink():
    from fakematlab.console.apps import recording_sink, set_app_sink

    recorder = recording_sink()
    previous = set_app_sink(recorder)
    yield recorder
    set_app_sink(previous)


def test_app_commands_emit_a_request(app_sink):
    from fakematlab.console import Interpreter

    it = Interpreter()
    assert it.run("G = tf([1], [1, 2, 1])").ok
    assert it.run("ltiview(G, closed=feedback(G, 1))").ok
    assert app_sink.last.app == "ltiview"
    assert list(app_sink.last.systems) == ["sys1", "closed"]

    assert it.run("sisotool(G)").ok
    assert app_sink.last.app == "sisotool"
    assert it.run("pidtuner(G, 'pid')").ok
    assert app_sink.last.options["kind"] == "PID"


def test_pidtune_returns_a_usable_controller(app_sink):
    from fakematlab.console import Interpreter

    it = Interpreter()
    assert it.run("G = tf([1], [1, 3, 3, 1])").ok
    result = it.run("C = pidtune(G, 'pid', wc=0.8, pm=55)")
    assert result.ok, result.error
    C = it.namespace["C"]
    assert isinstance(C, ctl.TransferFunction)
    # It composes the way MATLAB's does...
    assert it.run("T = feedback(C * G, 1)").ok
    # ...and carries the report that explains it.
    assert C.tuning.achieved_pm_deg == pytest.approx(55.0, rel=1e-4)


def test_pidtune_refuses_an_impossible_target_loudly():
    from fakematlab.console import Interpreter

    it = Interpreter()
    assert it.run("G = tf([1], [1, 3, 3, 1])").ok
    result = it.run("C = pidtune(G, 'pi', wc=1.2, pm=50)")
    assert result.error
    assert "subtracts* phase" in str(result.error)
    assert "use a PID" in str(result.error)


def test_the_apps_group_is_advertised_and_real():
    from fakematlab.console.api import _GROUPS, build_namespace

    namespace = build_namespace()
    assert "Apps" in _GROUPS
    for name in _GROUPS["Apps"]:
        assert callable(namespace[name])

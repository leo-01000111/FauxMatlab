"""
Modern control: state space, structure, feedback, observers, discrete time.

Checked against closed-form theory wherever one exists — the analytic Riccati
solution for the double integrator, the duality between placement and
observer design, the separation principle, and the Hankel error bound.
"""

from __future__ import annotations

import control as ctl
import numpy as np
import pytest

from fakematlab.core.discrete import (
    DiscreteError,
    c2d,
    d2c,
    deadbeat,
    jury,
    sample_rate_sweep,
    settling_samples,
)
from fakematlab.core.observers import (
    compensator,
    estimation_error_response,
    kalman,
    observer,
    reduced_observer,
)
from fakematlab.core.statefbk import (
    DesignError,
    acker,
    lqi,
    lqr,
    place,
)
from fakematlab.core.statespace import (
    StateSpaceError,
    analyse,
    minimal,
    modal_form,
    modal_response,
    similarity_transform,
    state_space,
)
from fakematlab.core.structural import (
    analyse_structure,
    balanced_realization,
    balanced_reduction,
    gramian,
    kalman_decomposition,
    reduction_error_bound,
)

# The ch.2 satellite: a double integrator.
SATELLITE = state_space([[0, 1], [0, 0]], [[0], [1]], [[1, 0]])
# A controllable, observable third-order plant.
THIRD = state_space([[0, 1, 0], [0, 0, 1], [-6, -11, -6]],
                    [[0], [0], [1]], [[1, 0, 0]])


def _freq(sys, w):
    return np.squeeze(ctl.frequency_response(sys, w).response)


# ──────────────────────────────────────────────────────────────
#  State space
# ──────────────────────────────────────────────────────────────

def test_similarity_transform_preserves_the_transfer_function():
    """The realisation is arbitrary; the transfer function is not."""
    rng = np.random.default_rng(0)
    T = rng.normal(size=(3, 3)) + 3 * np.eye(3)
    transformed = similarity_transform(THIRD, T)
    w = np.logspace(-2, 2, 60)
    assert np.allclose(_freq(THIRD, w), _freq(transformed, w), rtol=1e-8)


def test_singular_transform_is_refused():
    with pytest.raises(StateSpaceError, match="singular"):
        similarity_transform(THIRD, np.ones((3, 3)))


def test_modal_form_diagonalises_a():
    modal = modal_form(THIRD)
    A = np.asarray(modal.A)
    off_diagonal = A - np.diag(np.diag(A))
    assert np.max(np.abs(off_diagonal)) < 1e-8
    assert np.allclose(np.sort(np.linalg.eigvals(A).real),
                       np.sort(np.linalg.eigvals(np.asarray(THIRD.A)).real))


@pytest.mark.parametrize("A,B,C,expected", [
    (np.diag([-1.0, -5.0]), [[1.0], [0.0]], [[1.0, 1.0]], 1),   # uncontrollable
    (np.diag([-2.0, -3.0]), [[1.0], [1.0]], [[1.0, 0.0]], 1),   # unobservable
    (np.diag([-1.0, -2.0, -3.0, -4.0]),
     [[1.0], [1.0], [0.0], [0.0]], [[1.0, 0.0, 1.0, 0.0]], 1),  # both
    ([[0, 1], [-2, -3]], [[0], [1]], [[1, 0]], 2),              # already minimal
])
def test_minimal_removes_hidden_states_and_keeps_the_transfer_function(
        A, B, C, expected):
    """
    ``control.minreal`` needs slycot, so this is implemented with an SVD
    staircase; it must give the same answer.
    """
    sys = state_space(A, B, C)
    reduced = minimal(sys)
    assert reduced.nstates == expected

    w = np.logspace(-2, 2, 60)
    assert np.allclose(_freq(ctl.ss2tf(sys), w),
                       _freq(ctl.ss2tf(reduced), w), atol=1e-9)


def test_analyse_flags_a_non_minimal_realisation():
    sys = state_space(np.diag([-1.0, -5.0]), [[1.0], [0.0]], [[1.0, 1.0]])
    info = analyse(sys)
    assert not info.is_minimal
    assert info.n_minimal == 1
    assert any("cannot be seen" in n for n in info.notes)


def test_mode_residues_identify_the_invisible_mode():
    """An uncontrollable mode has no residue, so it never reaches the output."""
    sys = state_space(np.diag([-1.0, -5.0]), [[1.0], [0.0]], [[1.0, 1.0]])
    modes = {round(m.eigenvalue.real): m for m in analyse(sys).modes}
    assert modes[-1].visible
    assert not modes[-5].visible


def test_modal_response_sums_to_the_total():
    t = np.linspace(0, 5, 200)
    parts = modal_response(THIRD, t, x0=[1.0, 0.0, 0.0])
    total = parts.pop("total")
    assert np.allclose(sum(parts.values()), total, atol=1e-9)


# ──────────────────────────────────────────────────────────────
#  Structure
# ──────────────────────────────────────────────────────────────

def test_satellite_is_controllable_and_observable():
    report = analyse_structure(SATELLITE)
    assert report.controllable and report.observable
    assert report.ctrb_rank == 2 and report.obsv_rank == 2


def test_pbh_names_the_uncontrollable_mode():
    sys = state_space(np.diag([-1.0, -5.0]), [[1.0], [0.0]], [[1.0, 1.0]])
    report = analyse_structure(sys)
    assert not report.controllable
    assert report.uncontrollable_modes == [pytest.approx(-5.0)]
    # A stable uncontrollable mode is harmless, so it is still stabilizable.
    assert report.stabilizable


def test_an_unstable_uncontrollable_mode_is_not_stabilizable():
    sys = state_space(np.diag([-1.0, 2.0]), [[1.0], [0.0]], [[1.0, 1.0]])
    report = analyse_structure(sys)
    assert not report.stabilizable
    assert [m.eigenvalue.real for m in report.modes if m.fatal] == [
        pytest.approx(2.0)]


def test_gramian_solves_the_lyapunov_equation():
    """``control.gram`` needs slycot; scipy's Lyapunov solver does not."""
    sys = ctl.tf2ss(ctl.tf([1], [1, 2, 1]))
    A = np.asarray(sys.A)
    B = np.asarray(sys.B)
    Wc = gramian(sys, "c")
    assert np.linalg.norm(A @ Wc + Wc @ A.T + B @ B.T) < 1e-12

    C = np.asarray(sys.C)
    Wo = gramian(sys, "o")
    assert np.linalg.norm(A.T @ Wo + Wo @ A + C.T @ C) < 1e-12


def test_gramian_refuses_an_unstable_system():
    with pytest.raises(StateSpaceError, match="stable"):
        gramian(ctl.tf2ss(ctl.tf([1], [1, -1])), "c")


def test_balancing_equalises_the_gramians():
    sys = ctl.tf2ss(ctl.tf([1, 5], [1, 6, 11, 6]) * ctl.tf([1], [1, 10]))
    balanced, sigma = balanced_realization(sys)
    assert np.allclose(gramian(balanced, "c"), np.diag(sigma), atol=1e-9)
    assert np.allclose(gramian(balanced, "o"), np.diag(sigma), atol=1e-9)


@pytest.mark.parametrize("order", [1, 2, 3])
def test_reduction_stays_inside_the_hankel_error_bound(order):
    """``‖G − Gᵣ‖∞ ≤ 2·Σσᵢ`` over the discarded states."""
    sys = ctl.tf2ss(ctl.tf([1, 5], [1, 6, 11, 6]) * ctl.tf([1], [1, 10]))
    reduced, sigma = balanced_reduction(sys, order)
    assert reduced.nstates == order

    w = np.logspace(-2, 3, 800)
    error = np.max(np.abs(np.squeeze(ctl.frequency_response(sys, w).magnitude)
                          - np.squeeze(
                              ctl.frequency_response(reduced, w).magnitude)))
    assert error <= reduction_error_bound(sigma, order) * (1 + 1e-9)


def test_balancing_refuses_a_non_minimal_realisation():
    """
    A redundant state has σ = 0, and balancing divides by √σ — so this is a
    singular transformation, not a badly conditioned one.
    """
    sys = ctl.tf2ss(ctl.tf([1, 3], [1, 6, 11, 6]) * ctl.tf([1], [1, 10]))
    with pytest.raises(StateSpaceError, match="not minimal"):
        balanced_realization(sys)


def test_kalman_decomposition_counts_the_four_subspaces():
    sys = state_space(np.diag([-1.0, -2.0, -3.0, -4.0]),
                      [[1.0], [1.0], [0.0], [0.0]],
                      [[1.0, 0.0, 1.0, 0.0]])
    decomposition = kalman_decomposition(sys)
    assert decomposition.n_controllable_observable == 1
    assert decomposition.n_controllable_unobservable == 1
    assert decomposition.n_uncontrollable_observable == 1
    assert decomposition.n_uncontrollable_unobservable == 1
    # Only the controllable *and* observable part survives into the TF.
    assert decomposition.n_minimal == minimal(sys).nstates


# ──────────────────────────────────────────────────────────────
#  State feedback
# ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("R", [0.25, 1.0, 4.0])
def test_lqr_on_the_satellite_matches_the_analytic_riccati_solution(R):
    """
    For the double integrator with ``Q = I`` the Riccati equation can be
    solved by hand: ``p₂ = √R`` and ``p₃ = √(R(2√R + 1))``, giving

        K = [1/√R,  √((2√R + 1)/R)]
    """
    design = lqr(SATELLITE, np.eye(2), R)
    expected = [1.0 / np.sqrt(R), np.sqrt((2 * np.sqrt(R) + 1) / R)]
    assert np.allclose(design.K.ravel(), expected, rtol=1e-9)
    assert design.stable


def test_lqr_riccati_solution_satisfies_the_are():
    Q, R = np.eye(2), np.array([[1.0]])
    design = lqr(SATELLITE, Q, R)
    A, B = np.asarray(SATELLITE.A), np.asarray(SATELLITE.B)
    P = design.riccati
    residual = A.T @ P + P @ A - P @ B @ np.linalg.inv(R) @ B.T @ P + Q
    assert np.max(np.abs(residual)) < 1e-9


def test_place_and_acker_agree():
    """Two routes to the same eigenvalues must give the same gain."""
    desired = [-2.0, -3.0, -4.0]
    by_place = place(THIRD, desired)
    by_acker = acker(THIRD, desired)
    assert np.allclose(by_place.K, by_acker.K, atol=1e-7)
    assert np.allclose(np.sort(by_place.eigenvalues.real), sorted(desired),
                       atol=1e-9)


def test_reference_scaling_gives_unity_dc_gain():
    design = place(THIRD, [-2.0, -3.0, -4.0])
    assert float(ctl.dcgain(design.closed_loop)) == pytest.approx(1.0,
                                                                  abs=1e-9)


def test_placement_refuses_an_uncontrollable_system():
    sys = state_space(np.diag([-1.0, 2.0]), [[1.0], [0.0]], [[1.0, 1.0]])
    with pytest.raises(DesignError, match="not controllable"):
        place(sys, [-3.0, -4.0])


def test_placement_refuses_an_unpaired_complex_pole():
    with pytest.raises(DesignError, match="conjugate"):
        place(THIRD, [-1.0, -2.0 + 1j, -3.0])


def test_lqr_refuses_a_singular_r():
    with pytest.raises(DesignError, match="positive definite"):
        lqr(SATELLITE, np.eye(2), 0.0)


def test_lqr_refuses_an_unstabilizable_system():
    sys = state_space(np.diag([-1.0, 2.0]), [[1.0], [0.0]], [[1.0, 1.0]])
    with pytest.raises(DesignError, match="not stabilizable"):
        lqr(sys)


def test_lqi_adds_an_integrator_state():
    plant = state_space([[-1.0]], [[1.0]], [[1.0]])
    design = lqi(plant, np.diag([1.0, 10.0]), 1.0)
    assert design.K.size == 2            # one state gain, one integral gain
    assert design.stable


def test_lqr_has_the_guaranteed_gain_margin():
    """
    An LQR loop has at least 6 dB of gain margin and 60° of phase margin —
    a property pole placement makes no claim to.
    """
    design = lqr(THIRD, np.eye(3), 1.0)
    loop = ctl.ss2tf(ctl.ss(np.asarray(THIRD.A), np.asarray(THIRD.B),
                            design.K, 0))
    gm, pm, _sm, _wpc, _wgc, _wms = ctl.stability_margins(loop)
    gm_dB = 20 * np.log10(gm) if np.isfinite(gm) and gm > 0 else np.inf
    assert gm_dB >= 6.0
    assert pm >= 60.0 or not np.isfinite(pm)


# ──────────────────────────────────────────────────────────────
#  Observers
# ──────────────────────────────────────────────────────────────

def test_observer_places_the_estimation_error_eigenvalues():
    design = observer(THIRD, [-10.0, -11.0, -12.0])
    assert np.allclose(np.sort(design.eigenvalues.real), [-12, -11, -10],
                       atol=1e-8)
    assert design.stable


def test_observer_is_the_dual_of_state_feedback():
    """``L`` for ``(A, C)`` is ``Kᵀ`` for ``(Aᵀ, Cᵀ)`` — the same problem."""
    desired = [-10.0, -11.0, -12.0]
    L = observer(THIRD, desired).L
    dual = state_space(np.asarray(THIRD.A).T, np.asarray(THIRD.C).T,
                       np.eye(3))
    assert np.allclose(L.ravel(), place(dual, desired).K.ravel(), atol=1e-7)


def test_separation_principle_holds():
    """
    The closed-loop poles of an observer-based controller are exactly the
    union of the controller's and the observer's.
    """
    K = place(THIRD, [-2.0, -3.0, -4.0]).K
    L = observer(THIRD, [-10.0, -11.0, -12.0]).L
    comp = compensator(THIRD, K, L)

    assert comp.separation_holds
    assert comp.separation_error < 1e-8
    assert np.allclose(
        np.sort(comp.closed_loop_poles.real),
        np.sort(np.concatenate([[-2, -3, -4], [-10, -11, -12]])), atol=1e-7)


def test_estimation_error_decays_to_zero():
    L = observer(THIRD, [-10.0, -11.0, -12.0]).L
    t = np.linspace(0, 3, 300)
    error = estimation_error_response(THIRD, L, t, e0=[1.0, 1.0, 1.0])
    assert np.linalg.norm(error[:, 0]) > 1.0
    assert np.linalg.norm(error[:, -1]) < 1e-5


def test_noisier_sensor_gives_a_slower_kalman_filter():
    """Large V means an untrusted measurement, so the filter leans on its model."""
    quiet = kalman(THIRD, W=np.eye(3) * 0.1, V=np.array([[1.0]]))
    noisy = kalman(THIRD, W=np.eye(3) * 0.1, V=np.array([[100.0]]))
    assert max(noisy.eigenvalues.real) > max(quiet.eigenvalues.real)


def test_kalman_refuses_zero_measurement_noise():
    with pytest.raises(DesignError, match="positive definite"):
        kalman(THIRD, V=np.array([[0.0]]))


def test_observer_refuses_an_undetectable_system():
    sys = state_space(np.diag([-1.0, 3.0]), [[1.0], [1.0]], [[1.0, 0.0]])
    with pytest.raises(DesignError, match="not observable"):
        observer(sys, [-5.0, -6.0])


def test_reduced_observer_estimates_only_the_unmeasured_states():
    design = reduced_observer(THIRD, [-8.0, -9.0])
    assert len(design.eigenvalues) == 2
    assert np.allclose(np.sort(design.eigenvalues.real), [-9, -8], atol=1e-8)


def test_reduced_observer_refuses_when_everything_is_measured():
    sys = state_space([[-1.0, 0.0], [0.0, -2.0]], [[1.0], [1.0]], np.eye(2))
    with pytest.raises(DesignError, match="nothing left to estimate"):
        reduced_observer(sys, [-5.0])


# ──────────────────────────────────────────────────────────────
#  Discrete time
# ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("den", [[1, 1], [1, 1.2, 4], [1, 3, 3, 1]])
@pytest.mark.parametrize("dt", [0.01, 0.1])
def test_c2d_then_d2c_round_trips(den, dt):
    """python-control 0.10 has no ``d2c``; this one must invert ``c2d`` exactly."""
    original = ctl.tf2ss(ctl.tf([1], den))
    recovered = d2c(c2d(original, dt, "zoh"), "zoh")
    w = np.logspace(-2, 1, 80)
    assert np.allclose(_freq(original, w), _freq(recovered, w), atol=1e-9)


def test_d2c_refuses_a_system_with_no_continuous_equivalent():
    """A negative real discrete eigenvalue has no real matrix logarithm."""
    discrete = ctl.ss([[-0.5]], [[1.0]], [[1.0]], [[0.0]], 0.1)
    with pytest.raises(DiscreteError, match="no real continuous equivalent"):
        d2c(discrete, "zoh")


@pytest.mark.parametrize("roots,expected", [
    ([0.5, 0.3], True),
    ([0.5, 1.2], False),
    ([0.9, 0.9, 0.9], True),
    ([-0.99, 0.5], True),
    ([1.0, 0.5], False),
    ([0.99, -0.99], True),
])
def test_jury_matches_the_root_locations(roots, expected):
    result = jury(np.poly(roots))
    assert result.stable is expected
    assert (result.n_outside == 0) is expected


def test_jury_reports_which_condition_failed():
    result = jury(np.poly([1.5, 0.2]))
    assert not result.stable
    assert any(not passed for _text, passed, _v in result.conditions)
    assert "UNSTABLE" in result.summary()


@pytest.mark.parametrize("den", [[1, 1, 0], [1, 3, 3, 1], [1, 1]])
def test_deadbeat_settles_in_exactly_n_samples(den):
    """
    Every pole at ``z = 0`` makes ``A − BK`` nilpotent, so the state is
    exactly zero after ``n`` steps — a response with no continuous analogue.
    """
    discrete = c2d(ctl.tf2ss(ctl.tf([1], den)), 0.1, "zoh")
    K = deadbeat(discrete)
    A, B = np.asarray(discrete.A), np.asarray(discrete.B)
    n = discrete.nstates

    assert np.max(np.abs(np.linalg.matrix_power(A - B @ K, n))) < 1e-9
    assert settling_samples(discrete, K) == n


def test_deadbeat_refuses_a_continuous_system():
    with pytest.raises(DiscreteError, match="discrete-time idea"):
        deadbeat(SATELLITE)


def test_sampling_too_slowly_destabilises_a_tight_loop():
    """
    A zero-order hold adds ``ωT/2`` of phase lag. A loop with only 18° of
    margin runs out of it well before the Nyquist limit.
    """
    loop = ctl.tf([10], [1, 1, 0])          # PM ≈ 18°
    assert np.all(np.real(ctl.poles(ctl.feedback(loop, 1))) < 0)

    sweep = sample_rate_sweep(loop, [0.01, 0.4], close_loop=True)
    assert sweep[0.01]["stable"]
    assert not sweep[0.4]["stable"]
    assert sweep[0.4]["phase_lag_at_wc_deg"] > sweep[0.01]["phase_lag_at_wc_deg"]


def test_zoh_cannot_destabilise_an_already_stable_system():
    """Sampling maps the left half-plane into the unit disc."""
    stable = ctl.tf2ss(ctl.tf([4], [1, 1.2, 4]))
    for dt in (0.05, 0.5, 2.0):
        poles = np.atleast_1d(ctl.poles(c2d(stable, dt, "zoh")))
        assert np.all(np.abs(poles) < 1.0)
